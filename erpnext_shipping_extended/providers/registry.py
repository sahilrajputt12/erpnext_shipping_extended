from __future__ import annotations

from importlib import import_module


_PROVIDER_REGISTRY: dict[str, str] = {
	"Shiprocket": "erpnext_shipping_extended.providers.shiprocket.ShiprocketProvider",
}


def register_provider(provider_name: str, dotted_path: str) -> None:
	_PROVIDER_REGISTRY[provider_name] = dotted_path


def list_providers() -> list[str]:
	return sorted(_PROVIDER_REGISTRY.keys())


def get_provider(provider_name: str):
	if provider_name not in _PROVIDER_REGISTRY:
		raise KeyError(provider_name)

	dotted_path = _PROVIDER_REGISTRY[provider_name]
	module_path, cls_name = dotted_path.rsplit(".", 1)
	module = import_module(module_path)
	cls = getattr(module, cls_name)
	return cls()
