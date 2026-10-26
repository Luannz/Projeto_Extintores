# ==================== FORMS.PY ====================

from django import forms
from django.forms import ClearableFileInput
from django.contrib.auth.forms import UserCreationForm
from .models import Usuario, Extintor, Setor, Colaborador, Epi, RegistroEpi
from django.core.validators import RegexValidator

class MultipleFileInput(ClearableFileInput):
    allow_multiple_selected = True

class RegistroUsuarioForm(UserCreationForm):

    setor = forms.ModelChoiceField(
        queryset=Setor.objects.filter(ativo=True),
        label="Setor",
        required=False,
        empty_label="Selecione um setor...",
        widget=forms.Select(
            attrs={
                "class": "form-select text-muted",
            }
        ),
    )

    class Meta:
        model = Usuario
        fields = [
            "username",
            "setor",
            "password1",
            "password2",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Ajuste de estilos e placeholders nos campos
        self.fields["username"].label = "Usuário"
        self.fields["username"].widget.attrs.update(
            {
                "class": "form-control",
                "placeholder": "Seu Usuário",
            }
        )
        self.fields["password1"].widget.attrs.update(
            {
                "class": "form-control",
                "placeholder": "••••••••",
            }
        )
        self.fields["password2"].widget.attrs.update(
            {
                "class": "form-control",
                "placeholder": "••••••••",
            }
        )

        for field_name in ["username", "password1", "password2"]:
            if field_name in self.fields:
                self.fields[field_name].help_text = None

    def clean_username(self):
        username = self.cleaned_data.get("username")
        if username:
            return username.strip()  # Remove espaços no início e no final
        return username

    def save(self, commit=True):
        user = super().save(commit=False)
        # Associa a instância do setor (ou None se estiver em branco)
        user.setor = self.cleaned_data.get("setor")
        if commit:
            user.save()
        return user


class SetorForm(forms.ModelForm):
    class Meta:
        model = Setor
        fields = ["codigo", "nome", "ativo"]

        widgets = {
            "codigo": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Ex: ST01",
                }
            ),
            "nome": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Ex: Pesponto, Corte, Montagem",
                }
            ),
            "ativo": forms.CheckboxInput(
                attrs={
                    "class": "form-check-input",
                }
            ),
        }

        labels = {
            "codigo": "Código",
            "nome": "Nome do Setor",
            "ativo": "Setor Ativo",
        }


class ColaboradorForm(forms.ModelForm):
    class Meta:
        model = Colaborador
        fields = ["nome", "setor"]
        widgets = {
            "nome": forms.TextInput(attrs={"class": "form-control"}),
            "setor": forms.Select(attrs={"class": "form-select"}),
        }


class EpiForm(forms.ModelForm):
    class Meta:
        model = Epi
        fields = ["nome", "periodicidade_valor", "periodicidade_unidade"]
        widgets = {
            "nome": forms.TextInput(attrs={"class": "form-control"}),
            "periodicidade_valor": forms.NumberInput(attrs={"class": "form-control", "min": 1}),
            "periodicidade_unidade": forms.Select(attrs={"class": "form-select"}),
        }


class RegistroEpiForm(forms.ModelForm):
    class Meta:
        model = RegistroEpi
        fields = ["epi", "data_entrega"]
        widgets = {
            "epi": forms.Select(attrs={"class": "form-select"}),
            "data_entrega": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
        }

class ExtintorForm(forms.ModelForm):
    class Meta:
        model = Extintor
        fields = [
            "numero",
            "setor",
            "carga",
            "tipo",
            "data_vistoria",
            "data_vencimento",
            "situacao",
            "imagem",
        ]

        widgets = {
            "numero": forms.NumberInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Ex: 01",
                    "min": 1
                }
            ),
            "setor": forms.Select(
                attrs={
                    "class": "form-select",
                }
            ),
            "carga": forms.Select(
                attrs={
                    "class": "form-select",
                }
            ),
            "tipo": forms.Select(
                attrs={
                    "class": "form-select",
                }
            ),
            "data_vistoria": forms.DateInput(
                attrs={
                    "class": "form-control",
                    "type": "date",
                }
            ),
            "data_vencimento": forms.DateInput(
                attrs={
                    "class": "form-control",
                    "type": "date",
                }
            ),
            "situacao": forms.Select(
                attrs={
                    "class": "form-select",
                }
            ),
            "imagem": forms.ClearableFileInput(
                attrs={
                    "class": "form-control",
                    "accept": "image/*",
                }
            ),
        }

        labels = {
            "numero": "Número do Extintor",
            "setor": "Setor",
            "carga": "Carga",
            "tipo": "Tipo",
            "data_vistoria": "Data da Última Vistoria",
            "data_vencimento": "Data de Vencimento/Recarga",
            "situacao": "Situação",
            "imagem": "Foto do Extintor",
        }
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Exibe APENAS setores ativos na listagem do select
        self.fields['setor'].queryset = Setor.objects.filter(ativo=True).order_by('nome')

    def clean(self):
        cleaned_data = super().clean()
        numero = cleaned_data.get('numero')
        setor = cleaned_data.get('setor')
        
        carga = cleaned_data.get("carga")
        tipo = cleaned_data.get("tipo")

        combinacoes = {
            "PO_QUIMICO_ABC": ["ABC"],
            "PO_QUIMICO_BC": ["BC"],
            "CO2": ["BC"],
            "AGUA": ["A"],
            "ESPUMA": ["A"],
            "ACETATO": ["K"],
        }

        if carga and tipo:
            if tipo not in combinacoes.get(carga, []):
                self.add_error(
                    "tipo",
                    "O tipo selecionado não é compatível com a carga escolhida."
                )

        if numero and setor:
            # Query para verificar se já existe um extintor com este número e setor
            qs = Extintor.objects.filter(numero=numero, setor=setor)
            
            # Se for uma edição, ignora o próprio registro que está sendo editado
            if self.instance and self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)

            if qs.exists():
                # Associa o erro diretamente ao campo 'numero'
                self.add_error(
                    'numero', 
                    f'Já existe o extintor Nº {numero} cadastrado no setor "{setor}".'
                )

        return cleaned_data


class InspecaoRapidaForm(forms.ModelForm):

    class Meta:

        model = Extintor

        fields = [
            "data_vistoria",
            "situacao",
        ]