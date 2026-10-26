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

    # == SETORES ==
    path('setores/', views.listar_setores, name='listar_setores'),

    # == COLABORADORES ==
    path("colaboradores/",views.listar_colaboradores,name="listar_colaboradores"),
    path("colaborador/<int:colaborador_id>/epi/<int:registro_id>/deletar/",views.deletar_registro_epi,name="deletar_registro_epi"),

    # == EPIS ==
    path("epis/", views.listar_epis, name="listar_epis"),

    # == VINCULO EPIS == 
    path("epis/status/", views.status_epis, name="status_epis"),
    path("epis/colaborador/<int:colaborador_id>/",views.ficha_colaborador_epis,name="ficha_colaborador_epis"),

    # == EXTINTORES ==
    path('extintores/', views.listar_extintores, name='listar_extintores'),
    path('extintores/novo/', views.cadastrar_extintor, name='cadastrar_extintor'),
    path('extintores/<int:pk>/deletar/', views.deletar_extintor, name='deletar_extintor'),
    
    path('extintores/inspecao/', views.inspecao_extintores, name='inspecao_extintores'),
    path('extintores/<int:extintor_id>/editar-vistoria/', views.editar_vistoria_extintor, name='editar_vistoria_extintor'),

    # == GERADOR DOCUMDNOS ==
    path("gerar-documentos/", views.gerar_documentos, name="gerar_documentos"),

]

urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)