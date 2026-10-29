# ============= VIEWS.PY =====================
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required
from django.contrib.auth import login, logout, authenticate
from django.contrib import messages
from django.core.paginator import Paginator
from django.utils import timezone
from django.urls import reverse
from django.http import JsonResponse
from django.db import IntegrityError, transaction
from django.db.models import Case, When, Value, IntegerField, Q, Max, F, Count, Sum
from datetime import datetime, timedelta, date
from django.http import FileResponse
from django.forms import HiddenInput

from .forms import RegistroUsuarioForm, SetorForm, ExtintorForm, EmpresaForm
from .models import Setor, Extintor, Usuario, Empresa

import logging
logger = logging.getLogger(__name__)


def login_view(request):
    if request.user.is_authenticated:
        return redirect('inicio')
    if request.method == 'POST':
        username = request.POST['username']
        password = request.POST['password']
        user = authenticate(request, username=username, password=password)
        if user:
            login(request, user)
            return redirect('inicio')
        messages.error(request, 'Nome de usuário ou senha inválidos.')
    return render(request, 'core/login.html')


def logout_view(request):
    logout(request)
    return redirect('login')


@login_required
def cadastro_view(request):
    if request.method == 'POST':
        form = RegistroUsuarioForm(request.POST)
        if form.is_valid():
            user = form.save()
            # Removido o login(request, user) para não deslogar quem está cadastrando
            messages.success(request, f'Usuário {user.username} cadastrado com sucesso!')
            return redirect('inicio')
    else:
        form = RegistroUsuarioForm()

    return render(request, 'core/cadastro.html', {'form': form})


@login_required
def inicio_view(request):

    setores = Setor.objects.annotate(total_extintores=Count('extintores')).order_by('nome')
    empresas = Empresa.objects.filter(ativo=True).order_by('nome')

    # Listas para separar na tela inicial
    hoje = date.today()
    limite_alerta = hoje + timedelta(days=7)

    #2. AGORA TODOS OS EXTINTORES
    todos_extintores = Extintor.objects.select_related('setor').all()

    extintores_vencidos = []
    extintores_alerta = [] # Vencem em breve (30 dias) ou hoje
    limite_alerta_extintor = hoje + timedelta(days=30)

    for extintor in todos_extintores:
        vencimento = extintor.data_vencimento
        if vencimento < hoje:
            extintores_vencidos.append(extintor)
        elif hoje <= vencimento <= limite_alerta_extintor:
            extintores_alerta.append(extintor)

    # Métricas
    total_pendencias_extintor = len(extintores_vencidos) + len(
        extintores_alerta
    )

    return render(request,"core/inicio.html",{
            "empresas": empresas,
            "setores": setores,
            "extintores_vencidos": extintores_vencidos,
            "extintores_alerta": extintores_alerta,
            "total_pendencias_extintor": total_pendencias_extintor,
        },
    )


def csrf_failure_view(request, reason=""):
    # Adiciona a mensagem que o usuário vai ler ao chegar no login
    messages.warning(request, "Sua sessão expirou por inatividade. Por favor, entre novamente.")
    return redirect('login')


# ============= EMPRESAS ============

@login_required
def listar_empresas(request):
    hoje = timezone.localdate()
    empresas_list = Empresa.objects.annotate(
        total_setores=Count('setores', distinct=True),
        total_extintores=Count('setores__extintores', distinct=True),
        total_vencidos=Count(
            'setores__extintores',
            filter=Q(setores__extintores__data_vencimento__lt=hoje),
            distinct=True,
        ),
    ).order_by('nome')

    busca = request.GET.get("busca", "").strip()
    if busca:
        empresas_list = empresas_list.filter(Q(nome__icontains=busca) | Q(cnpj__icontains=busca))

    form = EmpresaForm()
    if request.method == "POST":
        empresa_id = request.POST.get("empresa_id")
        if empresa_id:
            empresa = get_object_or_404(Empresa, pk=empresa_id)
            form_post = EmpresaForm(request.POST, instance=empresa)
            msg = f'Empresa "{empresa.nome}" atualizada com sucesso!'
        else:
            form_post = EmpresaForm(request.POST)
            msg = 'Empresa cadastrada com sucesso!'

        if form_post.is_valid():
            form_post.save()
            messages.success(request, msg)
            return redirect("listar_empresas")
        form = form_post  # reexibe com os erros

    empresas = Paginator(empresas_list, 10).get_page(request.GET.get("page"))
    return render(request, "core/empresas_lista.html", {
        "empresas": empresas, "form": form, "busca": busca,
    })


@login_required
def detalhe_empresa(request, pk):
    empresa = get_object_or_404(Empresa, pk=pk)
    hoje = timezone.localdate()
    limite = hoje + timedelta(days=30)

    # Cadastro rápido de setor dentro da própria empresa
    form_setor = SetorForm(request.POST or None, initial={"empresa": empresa.pk})
    form_setor.fields["empresa"].widget = HiddenInput()
    if request.method == "POST":
        if form_setor.is_valid():
            form_setor.save()
            messages.success(request, "Setor cadastrado com sucesso!")
            return redirect("detalhe_empresa", pk=empresa.pk)

    setores = empresa.setores.annotate(
        total=Count('extintores'),
        vencidos=Count('extintores', filter=Q(extintores__data_vencimento__lt=hoje)),
        a_vencer=Count('extintores', filter=Q(
            extintores__data_vencimento__gte=hoje,
            extintores__data_vencimento__lte=limite,
        )),
    ).order_by('nome')

    extintores_qs = Extintor.objects.filter(setor__empresa=empresa).select_related('setor')

    setor_filtro = request.GET.get("setor", "").strip()
    extintores_list = extintores_qs
    if setor_filtro:
        extintores_list = extintores_list.filter(setor_id=setor_filtro)
    extintores_list = extintores_list.order_by('setor__nome', 'numero')

    extintores = Paginator(extintores_list, 15).get_page(request.GET.get("page"))

    return render(request, "core/empresa_detalhe.html", {
        "empresa": empresa,
        "setores": setores,
        "extintores": extintores,
        "setor_filtro": setor_filtro,
        "form_setor": form_setor,
        "hoje": hoje,
        "total_extintores": extintores_qs.count(),
        "total_vencidos": extintores_qs.filter(data_vencimento__lt=hoje).count(),
        "total_a_vencer": extintores_qs.filter(data_vencimento__range=(hoje, limite)).count(),
    })




# ============= SETORES ============

@login_required
def listar_setores(request):
    # Conta quantos extintores cada setor tem atrelado  o related_name na ForeignKey é 'extintores'
    setores_list = Setor.objects.annotate(total_extintores=Count('extintores')).order_by('nome')
    form = SetorForm(request.POST or None)

    if request.method == 'POST':
        setor_id = request.POST.get('setor_id')
        if setor_id:
            setor = get_object_or_404(Setor, pk=setor_id)
            
            # --- VALIDAÇÃO NO BACKEND ---
            # Verifica se o checkbox 'ativo' NÃO veio no POST (ou seja, o usuário quer desativar)
            quer_desativar = 'ativo' not in request.POST 
            tem_extintores = setor.extintores.exists()

            if quer_desativar and tem_extintores:
                messages.error(
                    request, 
                    f'Não é possível desativar o setor "{setor.nome}" pois existem {setor.extintores.count()} extintores cadastrados nele.'
                )
                return redirect('listar_setores')
            # ----------------------------

            form_edit = SetorForm(request.POST, instance=setor)
            if form_edit.is_valid():
                form_edit.save()
                messages.success(request, f'Setor "{setor.nome}" atualizado com sucesso!')
                return redirect('listar_setores')
        else:
            if form.is_valid():
                form.save()
                messages.success(request, 'Setor cadastrado com sucesso!')
                return redirect('listar_setores')

    paginator = Paginator(setores_list, 10)
    page_number = request.GET.get('page')
    setores = paginator.get_page(page_number)

    return render(request, 'core/setores_lista.html', {
        'setores': setores,
        'form': form,
    })

# ============ EXTINTORES ===============

def listar_extintores(request):
    """
    View responsável por listar os extintores cadastrados (com paginação)
    e processar edições enviadas via Modal.
    """

    # Lógica para processar EDIÇÃO via Modal (caso enviada a partir da lista)
    if request.method == 'POST':
        extintor_id = request.POST.get('extintor_id')
        if extintor_id:
            extintor = get_object_or_404(Extintor, pk=extintor_id)
            form_edit = ExtintorForm(
                request.POST,
                request.FILES,
                instance=extintor
            )
            if form_edit.is_valid():
                form_edit.save()
                messages.success(request, f'Extintor "{extintor.numero}" atualizado com sucesso!')
                return redirect('listar_extintores')
            else:
                messages.error(request, 'Erro ao atualizar o extintor. Verifique os campos.')

    # QuerySet base
    extintores_list = Extintor.objects.select_related('setor').all().order_by('numero', 'setor__nome')

    # Filtro por Setor
    setor_filtro = request.GET.get("setor", "").strip()
    if setor_filtro:
        extintores_list = extintores_list.filter(setor_id=setor_filtro)

    # Filtro por Empresa
    empresa_filtro = request.GET.get("empresa", "").strip()
    if empresa_filtro:
        extintores_list = extintores_list.filter(setor__empresa_id=empresa_filtro)

    # Filtro por Número
    numero_filtro = request.GET.get("numero", "").strip()
    if numero_filtro and numero_filtro.isdigit():
        extintores_list = extintores_list.filter(numero=int(numero_filtro))

    # Paginação (10 por página)
    paginator = Paginator(extintores_list, 10)
    page_number = request.GET.get('page')
    extintores = paginator.get_page(page_number)

    # Busca a lista de setores cadastrados para popular o select de busca
    setores = Setor.objects.all().order_by('nome')
    empresas = Empresa.objects.filter(ativo=True).order_by('nome')

    # Passamos o form genérico para alimentar os selects nos modais de edição
    form = ExtintorForm()

    return render(request, 'core/extintores_lista.html', {
        'extintores': extintores,
        'setores': setores,
        "empresas": empresas,
        'setor_filtro': setor_filtro,
        'numero_filtro': numero_filtro,
        'form': form
    })


def cadastrar_extintor(request):
    """
    View responsável exclusivamente pela exibição e processamento
    do formulário de criação de um novo extintor.
    """
    if request.method == 'POST':
        form = ExtintorForm(request.POST, request.FILES)
        if form.is_valid():
            extintor = form.save()
            messages.success(request, f'Extintor Nº "{extintor.numero}" cadastrado com sucesso!')
            return redirect('listar_extintores')
    else:
        form = ExtintorForm()

    return render(request, 'core/cadastro_extintor.html', {'form': form})


@require_POST
def deletar_extintor(request, pk):
    """
    View para exclusão segura de um extintor. Aceita apenas requisições POST.
    """
    extintor = get_object_or_404(Extintor, pk=pk)
    numero_extintor = extintor.numero
    extintor.delete()
    
    messages.success(request, f'Extintor Nº "{numero_extintor}" removido com sucesso!')
    return redirect('listar_extintores')


def inspecao_extintores(request):
    hoje = timezone.localdate()

    # Pega a lista base com otimização
    extintores_list = Extintor.objects.select_related("setor")
    # ===== FILTROS =====

    # Setor
    setor_filtro = request.GET.get("setor")
    if setor_filtro:
        extintores_list = extintores_list.filter(setor_id=setor_filtro)

    # Empresa
    empresa_filtro = request.GET.get("empresa", "").strip()
    if empresa_filtro:
        extintores_list = extintores_list.filter(setor__empresa_id=empresa_filtro)

    # Situação
    situacao_filtro = request.GET.get("situacao")
    if situacao_filtro:
        extintores_list = extintores_list.filter(situacao=situacao_filtro)

    # Vencimento
    vencimento_filtro = request.GET.get("vencimento")
    if vencimento_filtro == "vencidos":
        extintores_list = extintores_list.filter(data_vencimento__lt=hoje)
    elif vencimento_filtro == "30":
        extintores_list = extintores_list.filter(
            data_vencimento__range=(hoje, hoje + timedelta(days=30))
        )
    elif vencimento_filtro == "60":
        extintores_list = extintores_list.filter(
            data_vencimento__range=(hoje, hoje + timedelta(days=60))
        )
    elif vencimento_filtro == "90":
        extintores_list = extintores_list.filter(
            data_vencimento__range=(hoje, hoje + timedelta(days=90))
        )
    elif vencimento_filtro == "em_dia":
        extintores_list = extintores_list.filter(data_vencimento__gt=hoje)

    # Data da última vistoria
    vistoria_filtro = request.GET.get("vistoria")
    if vistoria_filtro and vistoria_filtro.isdigit():
        dias = int(vistoria_filtro)
        limite = hoje - timedelta(days=dias)
        extintores_list = extintores_list.filter(data_vistoria__lte=limite)

    # Ordenação (opcional, igual ao dashboard)
    ordem_filtro = request.GET.get("ordem", "numero")
    extintores_list = extintores_list.order_by(ordem_filtro)

    if ordem_filtro == "numero":
        extintores_list = extintores_list.order_by("numero")
    else:
        # Aplica o filtro escolhido e usa o número como desempate
        extintores_list = extintores_list.order_by(ordem_filtro, "numero")

    # ===== PAGINAÇÃO =====
    paginator = Paginator(extintores_list, 20)  # 20 extintores por página
    page_number = request.GET.get("page")
    extintores_paginados = paginator.get_page(page_number)

    return render(
        request,
        "core/extintores_manutencao.html",
        {
            "extintores": extintores_paginados,
            "setores": Setor.objects.filter(ativo=True),
            "empresas": Empresa.objects.filter(ativo=True),
            # Filtros mantidos no contexto para preencher os selects no HTML
            "setor_atual": setor_filtro,
            "situacao_atual": situacao_filtro,
            "vencimento_atual": vencimento_filtro,
            "vistoria_atual": vistoria_filtro,
            "ordem_atual": ordem_filtro,
            "hoje": hoje,
        },
    )

@login_required
@require_POST
def editar_vistoria_extintor(request, extintor_id):
    extintor = get_object_or_404(Extintor, id=extintor_id)

    situacao = request.POST.get("situacao")
    data_vistoria_str = request.POST.get("data_vistoria")
    vencimento_str = request.POST.get("data_vencimento")

    if situacao:
        extintor.situacao = situacao

    # Converte string (YYYY-MM-DD) para objeto date do Python
    if data_vistoria_str:
        extintor.data_vistoria = datetime.strptime(data_vistoria_str, "%Y-%m-%d").date()

    if vencimento_str:
        extintor.data_vencimento = datetime.strptime(vencimento_str, "%Y-%m-%d").date()

    extintor.save()
    messages.success(request, f"Vistoria do extintor Nº {extintor.numero} atualizada com sucesso!")

    return redirect(request.META.get("HTTP_REFERER", "inspecao_extintores"))
