"""
Batch processing automation for referrals.
Handles bulk operations, scheduled tasks, and workflow automation.
"""

from datetime import datetime, timedelta
from typing import Callable, Optional

from rich.console import Console
from rich.progress import Progress, BarColumn, TaskProgressColumn, TextColumn

from referral_crm.models import session_scope, ReferralStatus, Priority
from referral_crm.services.referral_service import ReferralService
from referral_crm.services.provider_service import ProviderService

console = Console()


class BatchProcessor:
    """
    Batch processor for referral operations.

    Supports:
    - Auto-assigning providers to approved referrals
    - Sending reminder emails for stale referrals
    - Auto-escalating high-priority referrals
    - Bulk status updates
    - Report generation
    """

    def auto_assign_providers(
        self,
        dry_run: bool = False,
    ) -> dict:
        """
        Automatically assign providers to approved referrals that don't have one.

        Args:
            dry_run: If True, don't actually make changes

        Returns:
            dict with statistics
        """
        stats = {"processed": 0, "assigned": 0, "no_match": 0}

        with session_scope() as session:
            referral_service = ReferralService(session)
            provider_service = ProviderService(session)

            # Get approved referrals without providers
            referrals = referral_service.list(
                status=ReferralStatus.APPROVED,
                limit=100,
            )

            unassigned = [r for r in referrals if r.provider_id is None]
            console.print(f"Found {len(unassigned)} approved referrals without providers")

            for referral in unassigned:
                stats["processed"] += 1

                if not referral.service_requested:
                    stats["no_match"] += 1
                    continue

                # Find matching providers
                matches = provider_service.find_matching_providers(
                    service_type=referral.service_requested,
                    state=referral.claimant_state,
                    zip_code=referral.claimant_zip,
                    carrier_id=referral.carrier_id,
                    limit=1,
                )

                if matches:
                    best_match = matches[0]
                    provider = best_match["provider"]
                    rate = best_match.get("rate")

                    if not dry_run:
                        referral_service.update(
                            referral.id,
                            user="auto_assign",
                            provider_id=provider.id,
                            rate_schedule_id=rate.id if rate else None,
                            rate_amount=rate.rate_amount if rate else None,
                        )

                    stats["assigned"] += 1
                    console.print(f"  Referral #{referral.id} -> {provider.name}")
                else:
                    stats["no_match"] += 1

        action = "Would assign" if dry_run else "Assigned"
        console.print(f"\n[green]{action} {stats['assigned']} providers[/green]")
        return stats

    def escalate_stale_referrals(
        self,
        hours_threshold: int = 24,
        dry_run: bool = False,
    ) -> dict:
        """
        Escalate priority of referrals that have been pending too long.

        Args:
            hours_threshold: Hours after which to escalate
            dry_run: If True, don't actually make changes

        Returns:
            dict with statistics
        """
        stats = {"checked": 0, "escalated": 0}
        cutoff = datetime.utcnow() - timedelta(hours=hours_threshold)

        with session_scope() as session:
            referral_service = ReferralService(session)

            # Get pending referrals
            referrals = referral_service.list(
                status=ReferralStatus.PENDING,
                limit=200,
            )

            for referral in referrals:
                stats["checked"] += 1

                # Check if stale
                received = referral.received_at or referral.created_at
                if received < cutoff:
                    # Escalate if not already urgent
                    if referral.priority != Priority.URGENT:
                        new_priority = {
                            Priority.LOW: Priority.MEDIUM,
                            Priority.MEDIUM: Priority.HIGH,
                            Priority.HIGH: Priority.URGENT,
                        }.get(referral.priority, Priority.URGENT)

                        if not dry_run:
                            referral_service.update(
                                referral.id,
                                user="auto_escalate",
                                priority=new_priority,
                            )

                        stats["escalated"] += 1
                        console.print(
                            f"  Referral #{referral.id}: "
                            f"{referral.priority.value} -> {new_priority.value}"
                        )

        action = "Would escalate" if dry_run else "Escalated"
        console.print(f"\n[yellow]{action} {stats['escalated']} referrals[/yellow]")
        return stats

    def bulk_update_status(
        self,
        from_status: ReferralStatus,
        to_status: ReferralStatus,
        filter_fn: Optional[Callable] = None,
        dry_run: bool = False,
    ) -> dict:
        """
        Bulk update referral statuses.

        Args:
            from_status: Current status to filter by
            to_status: New status to set
            filter_fn: Optional additional filter function
            dry_run: If True, don't actually make changes

        Returns:
            dict with statistics
        """
        stats = {"checked": 0, "updated": 0}

        with session_scope() as session:
            referral_service = ReferralService(session)

            referrals = referral_service.list(status=from_status, limit=500)

            for referral in referrals:
                stats["checked"] += 1

                # Apply optional filter
                if filter_fn and not filter_fn(referral):
                    continue

                if not dry_run:
                    referral_service.update_status(
                        referral.id,
                        to_status,
                        user="bulk_update",
                        notes=f"Bulk update from {from_status.value} to {to_status.value}",
                    )

                stats["updated"] += 1

        action = "Would update" if dry_run else "Updated"
        console.print(f"\n[green]{action} {stats['updated']} referrals[/green]")
        return stats

    def generate_daily_report(self) -> dict:
        """
        Generate a daily summary report.

        Returns:
            dict with report data
        """
        today = datetime.utcnow().date()
        yesterday = today - timedelta(days=1)

        with session_scope() as session:
            referral_service = ReferralService(session)

            # Get counts
            counts = referral_service.count_by_status()

            # Get recent referrals
            recent = referral_service.list(limit=100)
            today_count = sum(
                1 for r in recent
                if r.created_at.date() == today
            )
            yesterday_count = sum(
                1 for r in recent
                if r.created_at.date() == yesterday
            )

            # Calculate averages
            completed = [
                r for r in recent
                if r.status == ReferralStatus.COMPLETED and r.completed_at
            ]
            avg_turnaround = None
            if completed:
                turnarounds = [
                    (r.completed_at - r.created_at).total_seconds() / 3600
                    for r in completed
                ]
                avg_turnaround = sum(turnarounds) / len(turnarounds)

            report = {
                "date": today.isoformat(),
                "counts_by_status": counts,
                "total_referrals": sum(counts.values()),
                "created_today": today_count,
                "created_yesterday": yesterday_count,
                "avg_turnaround_hours": avg_turnaround,
            }

            # Print report
            console.print()
            console.print(f"[bold]Daily Report - {today.isoformat()}[/bold]")
            console.print("=" * 40)
            console.print(f"Total Referrals: {report['total_referrals']}")
            console.print(f"Created Today: {report['created_today']}")
            console.print(f"Created Yesterday: {report['created_yesterday']}")
            if avg_turnaround:
                console.print(f"Avg Turnaround: {avg_turnaround:.1f} hours")
            console.print()
            console.print("[bold]By Status:[/bold]")
            for status, count in sorted(counts.items()):
                console.print(f"  {status}: {count}")

            return report

    def cleanup_old_referrals(
        self,
        days_old: int = 90,
        status: ReferralStatus = ReferralStatus.COMPLETED,
        dry_run: bool = True,
    ) -> dict:
        """
        Archive or delete old completed referrals.

        Args:
            days_old: Age threshold in days
            status: Only cleanup referrals in this status
            dry_run: If True, don't actually delete

        Returns:
            dict with statistics
        """
        stats = {"checked": 0, "deleted": 0}
        cutoff = datetime.utcnow() - timedelta(days=days_old)

        console.print(f"[yellow]Checking for referrals older than {days_old} days[/yellow]")

        with session_scope() as session:
            referral_service = ReferralService(session)

            referrals = referral_service.list(status=status, limit=500)

            for referral in referrals:
                stats["checked"] += 1

                if referral.completed_at and referral.completed_at < cutoff:
                    if dry_run:
                        console.print(f"  Would delete: #{referral.id} - {referral.claimant_name}")
                    else:
                        referral_service.delete(referral.id)
                        console.print(f"  Deleted: #{referral.id}")

                    stats["deleted"] += 1

        action = "Would delete" if dry_run else "Deleted"
        console.print(f"\n[red]{action} {stats['deleted']} old referrals[/red]")
        return stats


class WorkflowAutomation:
    """
    Automated workflow rules for referral processing.
    """

    def __init__(self):
        self.rules = []

    def add_rule(
        self,
        name: str,
        condition: Callable,
        action: Callable,
    ):
        """
        Add a workflow rule.

        Args:
            name: Rule name for logging
            condition: Function that takes a referral and returns bool
            action: Function that takes a referral and performs an action
        """
        self.rules.append({
            "name": name,
            "condition": condition,
            "action": action,
        })

    def process_referral(self, referral) -> list[str]:
        """
        Process a referral through all rules.

        Returns:
            List of rule names that were triggered
        """
        triggered = []

        for rule in self.rules:
            if rule["condition"](referral):
                rule["action"](referral)
                triggered.append(rule["name"])

        return triggered

    def process_all(self, referrals: list) -> dict:
        """
        Process multiple referrals.

        Returns:
            dict mapping rule names to count of times triggered
        """
        stats = {rule["name"]: 0 for rule in self.rules}

        with Progress(
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Processing referrals", total=len(referrals))

            for referral in referrals:
                triggered = self.process_referral(referral)
                for rule_name in triggered:
                    stats[rule_name] += 1
                progress.update(task, advance=1)

        return stats


# Example workflow rules
def create_default_workflow() -> WorkflowAutomation:
    """Create a workflow automation with default rules."""
    workflow = WorkflowAutomation()

    # Rule: Auto-escalate urgent keywords
    def has_urgent_keywords(referral):
        keywords = ["urgent", "asap", "emergency", "stat", "rush"]
        text = f"{referral.email_subject or ''} {referral.notes or ''}".lower()
        return any(kw in text for kw in keywords)

    def escalate_to_urgent(referral):
        with session_scope() as session:
            service = ReferralService(session)
            service.update(referral.id, user="workflow", priority=Priority.URGENT)

    workflow.add_rule(
        name="auto_escalate_urgent",
        condition=has_urgent_keywords,
        action=escalate_to_urgent,
    )

    return workflow
