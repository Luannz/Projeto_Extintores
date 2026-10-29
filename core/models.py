# ============== MODELS.PY ===================== #

from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Sum
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta
from django.dispatch import receiver
from django.db.models.signals import post_delete, pre_save
from django.core.validators import RegexValidator


username_validator_com_espaco = RegexValidator(
    regex=r"^[\w.@+-]+(?: [\w.@+-]+)*$",
    message="Informe um nome de usuário válido. Pode conter letras, números, caracteres @/./+/-/_ e espaços.",
    code="invalid_username",
)


class Empresa(models.Model):
    ativo = models.BooleanField(default=True)
    nome = models.CharField(max_length=150, unique=True, verbose_name="Nome / Razão Social")
    telefone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    endereco = models.CharField(max_length=255, blank=True, verbose_name="Endereço")
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['nome']
        verbose_name = 'Empresa'
        verbose_name_plural = 'Empresas'

    def __str__(self):
        return self.nome

class Setor(models.Model):
    empresa = models.ForeignKey(
        Empresa, on_delete=models.PROTECT,
        related_name="setores", verbose_name="Empresa",
    )
    ativo = models.BooleanField(default=True)
    codigo = models.CharField(max_length=10, blank=True, null=True)
    nome = models.CharField(max_length=100)

    class Meta:
        ordering = ['empresa__nome', 'nome']
        verbose_name = 'Setor'
        verbose_name_plural = 'Setores'
        constraints = [
            models.UniqueConstraint(fields=['empresa', 'nome'], name='unique_setor_nome_por_empresa'),
            models.UniqueConstraint(
                fields=['empresa', 'codigo'],
                condition=models.Q(codigo__isnull=False),
                name='unique_setor_codigo_por_empresa',
            ),
        ]

class Usuario(AbstractUser):
    # Sobrescreve o username do AbstractUser para aceitar espaços
    username = models.CharField(
        "nome de usuário",
        max_length=150,
        unique=True,
        help_text="Obrigatório. 150 caracteres ou menos. Letras, números, espaços e @/./+/-/_ apenas.",
        validators=[username_validator_com_espaco],
        error_messages={
            "unique": "Um usuário com esse nome já existe.",
        },
    )

    setor = models.ForeignKey(
        Setor,  # Usando a classe diretamente
        on_delete=models.PROTECT,
        related_name="usuarios",
        verbose_name="Setor",
        null=True,
        blank=True,
    )

    def __str__(self):
        return self.get_full_name() or self.username

    class Meta:
        verbose_name = "Usuário"
        verbose_name_plural = "Usuários"


class Extintor(models.Model):
    TIPOS_INCENDIO = [
        ("ABC", "ABC"),
        ("BC", "BC"),
        ("A", "A"),
        ("K", "K"),
    ]

    STATUS_CHOICES = [
        ("OK", "Em Dia / Regular"),
        ("PENDENTE", "Necessita Inspeção"),
        ("VENCIDO", "Vencido"),
        ("MANUTENCAO", "Em Manutenção"),
    ]

    CARGA_CHOICES = [
        ("PO_QUIMICO_ABC", "Pó Químico ABC"),
        ("PO_QUIMICO_BC", "Pó Químico BC"),
        ("CO2", "CO₂"),
        ("AGUA", "Água Pressurizada"),
        ("ESPUMA", "Espuma Mecânica"),
        ("ACETATO", "Acetato de Potássio"),
    ]

    setor = models.ForeignKey(
        Setor,
        on_delete=models.PROTECT,
        related_name="extintores",
        verbose_name="Setor",
    )

    # 1. CARGA (Agente extintor)
    carga = models.CharField(
        max_length=50,
        verbose_name="Carga (Agente Extintor)",
        help_text="Ex: Pó Químico, CO2, Água Pressurizada, Espuma Mecânica",
        choices=CARGA_CHOICES,
    )

    # 2. TIPO (Letras / Classe do Fogo)
    tipo = models.CharField(
        max_length=10,
        choices=TIPOS_INCENDIO,
        verbose_name="Tipo (Classe)",
        help_text="Ex: ABC, BC, A, K",
    )

    numero = models.IntegerField(verbose_name="Número do Extintor", blank=True, null=True)
    data_vistoria = models.DateField(verbose_name="Data da ÚLTIMA Vistoria")
    data_vencimento = models.DateField(verbose_name="Data de Vencimento/Recarga")
    situacao = models.CharField(
        max_length=15,
        choices=STATUS_CHOICES,
        default="OK",
        verbose_name="Status de Uso",
    )
    imagem = models.ImageField(
        upload_to="extintores/",
        null=True,
        blank=True,
        verbose_name="Foto do Extintor",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['numero', 'setor'], 
                name='unique_extintor_numero_por_setor'
            )
        ]

    def __str__(self):
        return f"Extintor {self.carga} {self.tipo} - {self.setor.nome}"

    def save(self, *args, **kwargs):
        # Regra automática: Se a data de vencimento passou e não está em manutenção, marca como VENCIDO
        if self.data_vencimento and self.data_vencimento < date.today():
            if self.situacao != "MANUTENCAO":
                self.situacao = "VENCIDO"
        elif self.situacao == "VENCIDO":
            # Se a data de vencimento for no futuro e estava VENCIDO, ajusta de volta para OK
            self.situacao = "OK"

        super().save(*args, **kwargs)

    @property
    def esta_vencido(self):
        return self.data_vencimento < date.today() if self.data_vencimento else False

# ==============================================================================
# SIGNALS PARA GERENCIAMENTO AUTOMÁTICO DE IMAGENS NA PASTA MEDIA
# ==============================================================================

@receiver(post_delete, sender=Extintor)
def apagar_imagem_ao_deletar_extintor(sender, instance, **kwargs):
    """
    Remove a foto do disco rígido quando o extintor for excluído do banco.
    """
    if instance.imagem and instance.imagem.storage.exists(instance.imagem.name):
        instance.imagem.delete(save=False)


@receiver(pre_save, sender=Extintor)
def apagar_imagem_antiga_ao_atualizar(sender, instance, **kwargs):
    """
    Apaga a foto antiga do disco caso uma nova foto seja enviada durante a edição.
    """
    if not instance.pk:
        # Se o objeto é novo (ainda não existe no banco), não há foto antiga para apagar
        return False

    try:
        # Busca o estado atual do extintor gravado no banco de dados
        extintor_antigo = Extintor.objects.get(pk=instance.pk)
    except Extintor.DoesNotExist:
        return False

    foto_antiga = extintor_antigo.imagem
    foto_nova = instance.imagem

    # Se existia uma foto antiga e ela foi substituída por uma nova (ou removida)
    if foto_antiga and foto_antiga != foto_nova:
        if foto_antiga.storage.exists(foto_antiga.name):
            foto_antiga.delete(save=False)