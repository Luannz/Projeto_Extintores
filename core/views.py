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

from .forms import RegistroUsuarioForm, SetorForm, ExtintorForm, ColaboradorForm, EpiForm, RegistroEpiForm
from .models import Setor, Extintor, Usuario, Colaborador, Epi, RegistroEpi

from .gerar_documentos import gerar_zip_documentos
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
    colaboradores = Colaborador.objects.select_related('setor').annotate(total_epis=Count('epis_vinculados')).order_by('nome')

    # 1. TODOS OS EPIS
    # Busca todos os registros trazendo os relacionamentos para evitar consultas extras ao banco (N+1)
    todos_registros = RegistroEpi.objects.select_related('colaborador', 'colaborador__setor', 'epi').all()

    # Listas para separar na tela inicial
    epis_vencidos = []
    epis_alerta = [] # Vencem nos próximos 7 dias ou hoje

    hoje = date.today()
    limite_alerta = hoje + timedelta(days=7)

    for registro in todos_registros:
        proxima = registro.data_proxima_troca
        if proxima < hoje:
            epis_vencidos.append(registro)
        elif hoje <= proxima <= limite_alerta:
            epis_alerta.append(registro)

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
    total_pendencias_epi = len(epis_vencidos) + len(epis_alerta)
    total_pendencias_extintor = len(extintores_vencidos) + len(
        extintores_alerta
    )

    return render(request,"core/inicio.html",{
            "setores": setores,
            "colaboradores": colaboradores,
            "epis_vencidos": epis_vencidos,
            "epis_alerta": epis_alerta,
            "extintores_vencidos": extintores_vencidos,
            "extintores_alerta": extintores_alerta,
            "total_pendencias_epi": total_pendencias_epi,
            "total_pendencias_extintor": total_pendencias_extintor,
            "total_pendencias": total_pendencias_epi + total_pendencias_extintor,
        },
    )


def csrf_failure_view(request, reason=""):
    # Adiciona a mensagem que o usuário vai ler ao chegar no login
    messages.warning(request, "Sua sessão expirou por inatividade. Por favor, entre novamente.")
    return redirect('login')


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


# ============= COLABORADORES ===============

@login_required
def listar_colaboradores(request):
    colaboradores_list = (
        Colaborador.objects.select_related("setor")
        .annotate(total_epis=Count("epis_vinculados"))
        .order_by("nome")
    )

    #captura os parametros de busca GET que vem do template
    busca = request.GET.get("busca","").strip()
    setor_id = request.GET.get("setor", "").strip()

    # aqui aplica os filtros SE tiver algum deles
    if busca:
        colaboradores_list = colaboradores_list.filter(
            Q(nome__icontains=busca)
        )

    if setor_id:
        colaboradores_list = colaboradores_list.filter(setor_id=setor_id)

    form = ColaboradorForm(request.POST or None)
    if request.method == "POST":
        colaborador_id = request.POST.get("colaborador_id")
        if colaborador_id:
            # Edição
            colaborador = get_object_or_404(Colaborador, pk=colaborador_id)
            form_edit = ColaboradorForm(request.POST, instance=colaborador)
            if form_edit.is_valid():
                form_edit.save()
                messages.success(
                    request,
                    f'Colaborador "{colaborador.nome}" atualizado com sucesso!',
                )
                return redirect("listar_colaboradores")
        else:
            # Criação
            if form.is_valid():
                form.save()
                messages.success(
                    request, "Colaborador cadastrado com sucesso!"
                )
                return redirect("listar_colaboradores")

    paginator = Paginator(colaboradores_list, 10)
    page_number = request.GET.get("page")
    colaboradores = paginator.get_page(page_number)

    setores = Setor.objects.filter(ativo=True).order_by("nome")
    
    return render(
        request,
        "core/colaboradores_lista.html",
        {
            "colaboradores": colaboradores,
            "form": form,
            "setores": setores,
            "busca": busca,
            "setor_selecionado": setor_id,
        },
    )

# =============== EPI'S ===================

@login_required
def listar_epis(request):
    epis_list = Epi.objects.annotate(
        total_registros=Count("registros")
    ).order_by("nome")
    form = EpiForm(request.POST or None)

    if request.method == "POST":
        epi_id = request.POST.get("epi_id")
        if epi_id:
            # Edição
            epi = get_object_or_404(Epi, pk=epi_id)
            form_edit = EpiForm(request.POST, instance=epi)
            if form_edit.is_valid():
                form_edit.save()
                messages.success(
                    request, f'EPI "{epi.nome}" atualizado com sucesso!'
                )
                return redirect("listar_epis")
        else:
            # Criação
            if form.is_valid():
                form.save()
                messages.success(request, "EPI cadastrado com sucesso!")
                return redirect("listar_epis")

    paginator = Paginator(epis_list, 10)
    page_number = request.GET.get("page")
    epis = paginator.get_page(page_number)

    return render(
        request,
        "core/epis_lista.html",
        {
            "epis": epis,
            "form": form,
        },
    )

# ============ VÍNCULO DE EPIS =============

@login_required
def status_epis(request):
    """Lista de Colaboradores com busca e filtros para o técnico de segurança."""
    query = request.GET.get("q", "").strip()
    setor_id = request.GET.get("setor", "").strip()

    # Verifica se algum filtro foi aplicado
    tem_filtro = bool(query or setor_id)

    if tem_filtro:
        colaboradores_list = Colaborador.objects.select_related(
            "setor"
        ).annotate(
            total_epis=Count("epis_vinculados"),
        )

        if query:
            colaboradores_list = colaboradores_list.filter(
                Q(nome__icontains=query)
            )

        if setor_id:
            colaboradores_list = colaboradores_list.filter(setor_id=setor_id)

        colaboradores_list = colaboradores_list.order_by("nome")
    else:
        # Se nenhum filtro for aplicado, não busca nenhum registro no banco
        colaboradores_list = Colaborador.objects.none()

    # Paginação ajustada para 20 itens por página
    paginator = Paginator(colaboradores_list, 20)
    page_number = request.GET.get("page")
    colaboradores = paginator.get_page(page_number)

    setores = Setor.objects.filter(ativo=True).order_by("nome")

    return render(
        request,
        "core/status_epis.html",
        {
            "colaboradores": colaboradores,
            "setores": setores,
            "query": query,
            "setor_selecionado": setor_id,
            "tem_filtro": tem_filtro,
        },
    )


@login_required
def ficha_colaborador_epis(request, colaborador_id):
    """Ficha do Colaborador mostrando todos os seus EPIs e status de troca."""
    colaborador = get_object_or_404(
        Colaborador.objects.select_related("setor"), pk=colaborador_id
    )

    registros = RegistroEpi.objects.filter(
        colaborador=colaborador
    ).select_related("epi")

    form = RegistroEpiForm()

    if request.method == "POST":
        registro_id = request.POST.get("registro_id", "").strip()

        # EDIÇÃO DE EPI JÁ ATRIBUÍDO
        if registro_id:
            registro = get_object_or_404(
                RegistroEpi, pk=registro_id, colaborador=colaborador
            )
            form = RegistroEpiForm(request.POST, instance=registro)
            if form.is_valid():
                form.save()
                messages.success(
                    request,
                    f'Entrega do EPI "{registro.epi.nome}" renovada com sucesso!',
                )
                return redirect("ficha_colaborador_epis", colaborador_id=colaborador.id)
            else:
                messages.error(request, "Erro ao renovar a entrega do EPI. Verifique os dados.")

        # NOVO VÍNCULO DE EPI
        else:
            form = RegistroEpiForm(request.POST)
            if form.is_valid():
                novo_registro = form.save(commit=False)
                novo_registro.colaborador = colaborador
                novo_registro.save()
                messages.success(request, "Novo EPI vinculado/entregue com sucesso!")
                return redirect("ficha_colaborador_epis", colaborador_id=colaborador.id)
            else:
                messages.error(
                    request,
                    "Não foi possível vincular o EPI. Verifique se este EPI já não está atribuído ao colaborador ou se faltam informações.",
                )

    return render(
        request,
        "core/status_epi_usuario.html",
        {
            "colaborador": colaborador,
            "registros": registros,
            "form": form,
        },
    )

@login_required
@require_POST
def deletar_registro_epi(request, colaborador_id, registro_id):
    """Exclui o vínculo de um EPI específico do colaborador."""
    colaborador = get_object_or_404(Colaborador, pk=colaborador_id)
    registro = get_object_or_404(RegistroEpi, pk=registro_id, colaborador=colaborador)
    
    nome_epi = registro.epi.nome
    registro.delete()
    
    messages.success(request, f'O EPI "{nome_epi}" foi removido do colaborador com sucesso.')
    return redirect("ficha_colaborador_epis", colaborador_id=colaborador.id)


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

    # Passamos o form genérico para alimentar os selects nos modais de edição
    form = ExtintorForm()

    return render(request, 'core/extintores_lista.html', {
        'extintores': extintores,
        'setores': setores,
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


# ============ GERADOR DE DOCUMENTOS =============

@login_required
def gerar_documentos(request):
    if request.method == "POST":
        planilha = request.FILES.get("planilha")
        modelo = request.FILES.get("modelo")

        if not planilha or not modelo:
            messages.error(request, "Envie a planilha e o modelo.")
        elif not planilha.name.lower().endswith((".xlsx", ".xls")):
            messages.error(request, "A planilha precisa ser um arquivo Excel (.xlsx ou .xls).")
        elif not modelo.name.lower().endswith(".docx"):
            messages.error(request, "O modelo precisa ser um arquivo Word (.docx).")
        else:
            try:
                zip_buffer = gerar_zip_documentos(planilha, modelo)
            except Exception:
                logger.exception("Erro ao gerar documentos")
                messages.error(request, "Não foi possível processar os arquivos. Confira o formato da planilha e do modelo.")
            else:
                return FileResponse(
                    zip_buffer,
                    as_attachment=True,
                    filename="documentos_gerados.zip",
                )

    return render(request, "core/gerar_documentos.html")