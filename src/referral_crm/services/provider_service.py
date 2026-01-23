"""
Provider service for managing providers and rate lookup.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from referral_crm.models import Provider, ProviderService as ProviderServiceModel, RateSchedule


class ProviderService:
    """Service for managing providers and finding matches."""

    def __init__(self, session: Session):
        self.session = session

    def create(
        self,
        name: str,
        npi: Optional[str] = None,
        **kwargs,
    ) -> Provider:
        """Create a new provider."""
        provider = Provider(name=name, npi=npi, **kwargs)
        self.session.add(provider)
        self.session.commit()
        self.session.refresh(provider)
        return provider

    def get(self, provider_id: int) -> Optional[Provider]:
        """Get a provider by ID."""
        return self.session.query(Provider).filter(Provider.id == provider_id).first()

    def get_by_npi(self, npi: str) -> Optional[Provider]:
        """Get a provider by NPI."""
        return self.session.query(Provider).filter(Provider.npi == npi).first()

    def list(
        self,
        service_type: Optional[str] = None,
        state: Optional[str] = None,
        accepting_new: Optional[bool] = None,
        active_only: bool = True,
        limit: int = 100,
    ) -> list[Provider]:
        """List providers with optional filtering."""
        query = self.session.query(Provider)

        if active_only:
            query = query.filter(Provider.is_active == True)
        if accepting_new is not None:
            query = query.filter(Provider.accepting_new == accepting_new)
        if state:
            query = query.filter(Provider.state == state.upper())
        if service_type:
            query = query.join(Provider.services).filter(
                ProviderServiceModel.service_type == service_type,
                ProviderServiceModel.is_active == True,
            )

        return query.order_by(Provider.name).limit(limit).all()

    def update(self, provider_id: int, **kwargs) -> Optional[Provider]:
        """Update a provider."""
        provider = self.get(provider_id)
        if not provider:
            return None

        for field, value in kwargs.items():
            if hasattr(provider, field):
                setattr(provider, field, value)

        provider.updated_at = datetime.utcnow()
        self.session.commit()
        self.session.refresh(provider)
        return provider

    def add_service(
        self,
        provider_id: int,
        service_type: str,
    ) -> Optional[ProviderServiceModel]:
        """Add a service to a provider."""
        provider = self.get(provider_id)
        if not provider:
            return None

        # Check if service already exists
        existing = (
            self.session.query(ProviderServiceModel)
            .filter(
                ProviderServiceModel.provider_id == provider_id,
                ProviderServiceModel.service_type == service_type,
            )
            .first()
        )
        if existing:
            existing.is_active = True
            self.session.commit()
            return existing

        service = ProviderServiceModel(
            provider_id=provider_id,
            service_type=service_type,
        )
        self.session.add(service)
        self.session.commit()
        self.session.refresh(service)
        return service

    def find_matching_providers(
        self,
        service_type: str,
        state: Optional[str] = None,
        zip_code: Optional[str] = None,
        carrier_id: Optional[int] = None,
        limit: int = 10,
    ) -> list[dict]:
        """
        Find providers that match the given criteria.
        Returns a list of dicts with provider info and match scores.
        """
        # Get base matching providers
        providers = self.list(
            service_type=service_type,
            state=state,
            accepting_new=True,
            active_only=True,
            limit=limit * 2,  # Get extra to allow for scoring/filtering
        )

        results = []
        for provider in providers:
            score = self._calculate_match_score(
                provider,
                service_type=service_type,
                state=state,
                zip_code=zip_code,
            )

            # Get applicable rate if carrier specified
            rate = None
            if carrier_id:
                rate = self._get_applicable_rate(
                    carrier_id=carrier_id,
                    service_type=service_type,
                    state=provider.state,
                )

            results.append({
                "provider": provider,
                "score": score,
                "rate": rate,
                "wait_days": provider.avg_wait_days,
            })

        # Sort by score descending
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:limit]

    def _calculate_match_score(
        self,
        provider: Provider,
        service_type: str,
        state: Optional[str] = None,
        zip_code: Optional[str] = None,
    ) -> float:
        """
        Calculate a match score (0-100) for a provider.
        Higher scores are better matches.
        """
        score = 50.0  # Base score

        # State match
        if state and provider.state == state.upper():
            score += 20.0

        # Accepting new patients
        if provider.accepting_new:
            score += 10.0

        # Wait time factor
        if provider.avg_wait_days is not None:
            if provider.avg_wait_days <= 3:
                score += 15.0
            elif provider.avg_wait_days <= 7:
                score += 10.0
            elif provider.avg_wait_days <= 14:
                score += 5.0

        # ZIP code proximity (simplified - first 3 digits match)
        if zip_code and provider.zip_code:
            if provider.zip_code[:3] == zip_code[:3]:
                score += 15.0
            elif provider.zip_code[:2] == zip_code[:2]:
                score += 5.0

        return min(score, 100.0)

    def _get_applicable_rate(
        self,
        carrier_id: int,
        service_type: str,
        state: Optional[str] = None,
    ) -> Optional[RateSchedule]:
        """Find the applicable rate schedule for a carrier/service/state."""
        query = self.session.query(RateSchedule).filter(
            RateSchedule.carrier_id == carrier_id,
            RateSchedule.service_type == service_type,
        )

        if state:
            # Try state-specific first
            state_rate = query.filter(RateSchedule.state == state.upper()).first()
            if state_rate:
                return state_rate

        # Fall back to any rate for this carrier/service
        return query.first()


class RateService:
    """Service for managing rate schedules."""

    def __init__(self, session: Session):
        self.session = session

    def create(
        self,
        carrier_id: int,
        service_type: str,
        rate_amount: float,
        **kwargs,
    ) -> RateSchedule:
        """Create a new rate schedule."""
        rate = RateSchedule(
            carrier_id=carrier_id,
            service_type=service_type,
            rate_amount=rate_amount,
            **kwargs,
        )
        self.session.add(rate)
        self.session.commit()
        self.session.refresh(rate)
        return rate

    def get(self, rate_id: int) -> Optional[RateSchedule]:
        """Get a rate schedule by ID."""
        return self.session.query(RateSchedule).filter(RateSchedule.id == rate_id).first()

    def list_by_carrier(self, carrier_id: int) -> list[RateSchedule]:
        """List all rate schedules for a carrier."""
        return (
            self.session.query(RateSchedule)
            .filter(RateSchedule.carrier_id == carrier_id)
            .order_by(RateSchedule.service_type, RateSchedule.state)
            .all()
        )

    def find_rate(
        self,
        carrier_id: int,
        service_type: str,
        state: Optional[str] = None,
        body_region: Optional[str] = None,
    ) -> Optional[RateSchedule]:
        """
        Find the most specific rate for given criteria.
        Tries from most specific to least specific.
        """
        query = self.session.query(RateSchedule).filter(
            RateSchedule.carrier_id == carrier_id,
            RateSchedule.service_type == service_type,
        )

        # Try most specific: state + body region
        if state and body_region:
            rate = query.filter(
                RateSchedule.state == state.upper(),
                RateSchedule.body_region == body_region,
            ).first()
            if rate:
                return rate

        # Try state only
        if state:
            rate = query.filter(
                RateSchedule.state == state.upper(),
                RateSchedule.body_region == None,
            ).first()
            if rate:
                return rate

        # Try body region only
        if body_region:
            rate = query.filter(
                RateSchedule.state == None,
                RateSchedule.body_region == body_region,
            ).first()
            if rate:
                return rate

        # Fall back to base rate
        return query.filter(
            RateSchedule.state == None,
            RateSchedule.body_region == None,
        ).first()

    def update(self, rate_id: int, **kwargs) -> Optional[RateSchedule]:
        """Update a rate schedule."""
        rate = self.get(rate_id)
        if not rate:
            return None

        for field, value in kwargs.items():
            if hasattr(rate, field):
                setattr(rate, field, value)

        self.session.commit()
        self.session.refresh(rate)
        return rate

    def delete(self, rate_id: int) -> bool:
        """Delete a rate schedule."""
        rate = self.get(rate_id)
        if not rate:
            return False

        self.session.delete(rate)
        self.session.commit()
        return True
