from django.shortcuts import render

def home(request):
    return render(request, 'home.html')

def health_check(request):
    from django.http import JsonResponse
    return JsonResponse({'status': 'ok', 'app': 'RailClub Connect'})
