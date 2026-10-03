from django.contrib import admin

from .models import BladeCard, ClothRoll, DipRun, Loft

admin.site.register(Loft)
admin.site.register(ClothRoll)
admin.site.register(DipRun)
admin.site.register(BladeCard)
