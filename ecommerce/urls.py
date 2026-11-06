from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

handler404 = 'core.views.error_404'
handler500 = 'core.views.error_500'

urlpatterns = [
    path(settings.ADMIN_URL, admin.site.urls),
    path('api/v1/fleet/', include('fleet.urls')),  # Mahitaji Fleet masters (fleet/api.py)
    path('', include('core.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
