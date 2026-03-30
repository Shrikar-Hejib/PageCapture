from django.urls import path
from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('workspace/', views.workspace, name='workspace'),
    path('api/crawl/', views.start_crawl, name='start_crawl'),
    path('api/generate-single/', views.generate_single_pdf, name='generate_single'),
    path('api/proxy/', views.proxy_page, name='proxy_page'),
    path('download/merged/', views.download_merged, name='download_merged'),
    path('download/zip/', views.download_zip, name='download_zip'),
]
