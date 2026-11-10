from django.contrib.auth.decorators import login_required
from django.shortcuts import render


@login_required
def home(request):
    return render(request, "audits/placeholder.html", {"heading": "Audits"})


@login_required
def issue_list(request):
    return render(request, "audits/placeholder.html", {"heading": "Issues"})


@login_required
def dashboard(request):
    return render(request, "audits/placeholder.html", {"heading": "Dashboard"})
