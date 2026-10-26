# ==================== URLS.PY ====================
from django.urls import path
from django.conf import settings
from django.conf.urls.static import static
from . import views

urlpatterns = [
    path('', views.inicio_view, name='inicio'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('cadastro/', views.cadastro_view, name='cadastro'),

    # == EMPRESAS ==
    path('empresas/', views.listar_empresas, name='listar_empresas'),
    path('empresas/<int:pk>/', views.detalhe_empresa, name='detalhe_empresa'),

    # == SETORES ==
    path('setores/', views.listar_setores, name='listar_setores'),

    # == COLABORADORES ==
    path("colaboradores/",views.listar_colaboradores,name="listar_colaboradores"),

    # == EXTINTORES ==
    path('extintores/', views.listar_extintores, name='listar_extintores'),
    path('extintores/novo/', views.cadastrar_extintor, name='cadastrar_extintor'),
    path('extintores/<int:pk>/deletar/', views.deletar_extintor, name='deletar_extintor'),
    
    path('extintores/inspecao/', views.inspecao_extintores, name='inspecao_extintores'),
    path('extintores/<int:extintor_id>/editar-vistoria/', views.editar_vistoria_extintor, name='editar_vistoria_extintor'),

]

urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)