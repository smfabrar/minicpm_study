"""Caller profiles belong to the study; each runtime request selects just one."""

from dataclasses import asdict, replace

from speech_contracts import RunSettings


def settings_for(settings, profile):
    return replace(settings, **{'caller_' + key: value for key, value in profile.items()})


def default_profiles(settings):
    selected = asdict(settings.caller)
    other = 'qwen3' if selected['backend'] == 'granite' else 'granite'
    alternate = replace(settings, caller_backend=other, caller_model='', caller_revision='',
                        caller_device=selected['device'], caller_quantization='none')
    return [selected, asdict(alternate.caller)]


def validate_profiles(profiles, settings):
    if not isinstance(profiles, list) or len(profiles) not in {0, 2}:
        raise ValueError('Select both caller profiles, or use single-caller settings')
    normalized = []
    for profile in profiles:
        if not isinstance(profile, dict) or set(profile) != {'backend', 'model', 'revision', 'device', 'quantization'}:
            raise ValueError('Each caller profile needs backend, model, revision, device and quantization')
        if any(not isinstance(value, str) or not value.strip() for value in profile.values()):
            raise ValueError('Caller profile fields must be non-empty text')
        normalized.append(asdict(settings_for(settings, profile).caller))
    if len({profile['backend'] for profile in normalized}) != len(normalized):
        raise ValueError('Select each caller backend once')
    return normalized


def run_caller(run):
    return run.caller_profile or asdict(RunSettings.from_dict(run.request.get('settings', {})).caller)
