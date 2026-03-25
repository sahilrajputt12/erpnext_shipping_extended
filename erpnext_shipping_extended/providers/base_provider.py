from __future__ import annotations

from abc import ABC, abstractmethod


class BaseShippingProvider(ABC):
	"""Stateless provider interface.

	Providers must not persist auth tokens to DB. Use in-memory caching only.
	"""

	provider_name: str

	@abstractmethod
	def authenticate(self) -> None:
		raise NotImplementedError

	@abstractmethod
	def fetch_shipping_rates(self, *, shipment_doc, **kwargs) -> list[dict]:
		raise NotImplementedError

	@abstractmethod
	def create_shipment(self, *, shipment_doc, service_info: dict, **kwargs) -> dict:
		raise NotImplementedError

	@abstractmethod
	def get_label(self, *, shipment_doc, **kwargs):
		raise NotImplementedError

	@abstractmethod
	def update_tracking(self, *, shipment_doc, **kwargs) -> dict | None:
		raise NotImplementedError

	def cancel_shipment(self, *, shipment_doc, **kwargs) -> dict | None:
		return None
