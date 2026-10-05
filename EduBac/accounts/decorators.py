from functools import wraps
from django.shortcuts import redirect
from django.contrib import messages


def login_required_simple(view_func):
    """Exige une session avec user_id."""
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not getattr(request, 'edubac_user', None):
            messages.info(request, 'Veuillez vous connecter.')
            return redirect('accounts:login')
        return view_func(request, *args, **kwargs)
    return _wrapped


def teacher_required(view_func):
    @login_required_simple
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        user = request.edubac_user
        if not user or user.role != 'teacher':
            messages.error(request, 'Accès réservé aux enseignants.')
            return redirect('education:home')
        return view_func(request, *args, **kwargs)
    return _wrapped


def student_required(view_func):
    @login_required_simple
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        user = request.edubac_user
        if not user or user.role != 'student':
            messages.error(request, 'Accès réservé aux élèves.')
            return redirect('education:home')
        return view_func(request, *args, **kwargs)
    return _wrapped
