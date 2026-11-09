"""Consolidate the latest Daily COB and current-year historical EOM snapshots.

Requires: pandas, openpyxl (for .xlsx input)
Run: python dashboard_tracker.py
"""

import csv
import logging
import os
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd


LOGGER = logging.getLogger(__name__)


class DashboardTracker:
    BASE_FOLDER = Path("/path/to/dashboard/files")
    FILE_PREFIX = "Dashboard"
    FILE_EXTENSION = ".xlsx"
    FILE_DATE_FORMAT = "%Y%m%d"
    MAX_LOOKBACK_BUSINESS_DAYS = 60
    TRACKER_COLUMNS = (
        "current_datetime", "previous_cob", "new_cob", "total_cobs"
    )
    EOM_VERSIONS = ("Daily", "Flash", "Final")

    def __init__(self, base_folder=None, mail_sender=None):
        self.base_folder = Path(base_folder or self.BASE_FOLDER)
        self._mail_sender = mail_sender
        self.base_folder.mkdir(parents=True, exist_ok=True)
        self.tracker_path = self.base_folder / "dashboard_tracker.csv"
        self.output_path = self.base_folder / "dashboard_consolidated.csv"
        self.create_tracker()

    @staticmethod
    def as_date(value):
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        raise TypeError("cob_date must be a datetime or date object")

    @staticmethod
    def shift_business_days(value, offset):
        """Shift by weekdays (Mon-Fri); market holidays are not included."""
        result = DashboardTracker.as_date(value)
        step = 1 if offset >= 0 else -1
        for _ in range(abs(offset)):
            result += timedelta(days=step)
            while result.weekday() >= 5:
                result += timedelta(days=step)
        return result

    @staticmethod
    def normalize_version(version):
        """Placeholder for future naming rules; currently no extra suffix."""
        return ""

    def generate_filename(self, cob_date, version):
        """Return (file_name, file_path, exists) for a date/version pair."""
        cob_date = self.as_date(cob_date)
        if version not in self.EOM_VERSIONS:
            raise ValueError(f"Unsupported version: {version!r}")

        # Keep the original version in the name because the current
        # normalization placeholder returns '' for ALL versions.
        suffix = self.normalize_version(version)
        if not isinstance(suffix, str):
            raise TypeError("normalize_version must return a string")
        file_name = (
            f"{self.FILE_PREFIX}_{cob_date.strftime(self.FILE_DATE_FORMAT)}"
            f"_{version}{suffix}{self.FILE_EXTENSION}"
        )
        file_path = self.base_folder / file_name
        return file_name, file_path, file_path.is_file()

    def create_tracker(self):
        """Create tracker with the expected header, but never overwrite it."""
        if self.tracker_path.exists():
            if not self.tracker_path.is_file():
                raise ValueError(f"Tracker is not a file: {self.tracker_path}")
            return False
        with self.tracker_path.open("x", newline="", encoding="utf-8") as file:
            csv.writer(file).writerow(self.TRACKER_COLUMNS)
        return True

    def get_latest_tracker(self):
        with self.tracker_path.open("r", newline="", encoding="utf-8") as file:
            reader = csv.DictReader(file)
            if reader.fieldnames != list(self.TRACKER_COLUMNS):
                raise ValueError("Tracker header does not match expected columns")
            last = None
            for row in reader:
                if row["new_cob"]:
                    last = row
            return last

    def find_latest_cob(self, today=None):
        """Start 3 business days before today and search backwards."""
        today = self.as_date(today or datetime.now())
        candidate = self.shift_business_days(today, -3)
        for _ in range(self.MAX_LOOKBACK_BUSINESS_DAYS):
            name, path, exists = self.generate_filename(candidate, "Daily")
            if exists:
                LOGGER.info("Latest source COB: %s (%s)", candidate, path)
                return candidate
            LOGGER.info("COB source missing: %s", name)
            candidate = self.shift_business_days(candidate, -1)
        raise FileNotFoundError(
            f"No Daily file found in {self.MAX_LOOKBACK_BUSINESS_DAYS} "
            "business-day checks"
        )

    def generate_daily_dates(self, cob_date):
        """Five Daily dates including finalized COB, oldest first."""
        cob_date = self.as_date(cob_date)
        return [self.shift_business_days(cob_date, i) for i in range(-4, 1)]

    def generate_eom_dates(self, cob_date):
        """Last weekday of each preceding month in the COB's calendar year."""
        cob_date = self.as_date(cob_date)
        result = []
        for month in range(1, cob_date.month):
            if month == 12:
                end = date(cob_date.year, 12, 31)
            else:
                end = date(cob_date.year, month + 1, 1) - timedelta(days=1)
            while end.weekday() >= 5:
                end -= timedelta(days=1)
            result.append(end)
        return result

    def build_file_inventory(self, cob_date):
        """Build distinct (COB, version) requests; fail on any missing file."""
        requested = [(day, "Daily") for day in self.generate_daily_dates(cob_date)]
        requested += [
            (day, version)
            for day in self.generate_eom_dates(cob_date)
            for version in self.EOM_VERSIONS
        ]

        # A Daily EOM date may already be among the five recent Daily dates.
        unique_requests = list(dict.fromkeys(requested))
        inventory = []
        missing = []
        for day, version in unique_requests:
            name, path, exists = self.generate_filename(day, version)
            inventory.append((day, version, path))
            if not exists:
                missing.append(name)
        if missing:
            raise FileNotFoundError(
                "Required historical source files are missing:\n- "
                + "\n- ".join(missing)
            )
        return inventory

    def read_file(self, file_path, cob_date, version):
        """Read a source file and label every row with its COB and version."""
        path = Path(file_path)
        df = pd.read_excel(path, engine="openpyxl")
        if df.empty:
            raise ValueError(f"Source file is empty: {path}")

        # Source metadata is set from the requested file identity.
        df["cob_date"] = self.as_date(cob_date).isoformat()
        df["version"] = version
        LOGGER.info("Read %s: %,d rows", path.name, len(df))
        return df

    def consolidate_daily(self, inventory):
        frames = [
            self.read_file(path, day, version)
            for day, version, path in inventory
            if version == "Daily"
        ]
        if not frames:
            raise ValueError("There are no Daily files to consolidate")
        return pd.concat(frames, ignore_index=True, copy=False)

    def consolidate_eom(self, inventory, daily_df):
        frames = [
            self.read_file(path, day, version)
            for day, version, path in inventory
            if version in ("Flash", "Final")
        ]
        if not frames:
            return daily_df
        return pd.concat([daily_df, *frames], ignore_index=True, copy=False)

    def save_consolidated(self, dataframe):
        """Write into same folder, then replace output after a full write."""
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".csv", prefix=".dashboard_",
                dir=self.base_folder, delete=False, encoding="utf-8", newline=""
            ) as tmp:
                temp_path = Path(tmp.name)
                dataframe.to_csv(tmp, index=False)
            os.replace(temp_path, self.output_path)
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)

    def update_tracker(self, cob_date):
        """Append record ONLY after the consolidated output was saved."""
        cob_date = self.as_date(cob_date)
        latest = self.get_latest_tracker()
        if latest and latest["new_cob"] == cob_date.isoformat():
            raise ValueError("COB is already concatenated")
        previous = latest["new_cob"] if latest else ""
        count = int(latest["total_cobs"]) + 1 if latest else 1
        with self.tracker_path.open("a", newline="", encoding="utf-8") as file:
            csv.writer(file).writerow([
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                previous,
                cob_date.isoformat(),
                count,
            ])

    def email_sender(self, subject, message, classification):
        """Send a monitoring email through the configured server mailer.

        The expected mailer signature is send(subject=..., message=...,
        classification=...). Supply a callable via mail_sender if your
        server's Mailer.send uses different argument names or needs recipients.
        """
        if not all(isinstance(x, str) and x.strip()
                   for x in (subject, message, classification)):
            raise ValueError("Email subject, message and classification are required")

        if self._mail_sender is not None:
            sender = self._mail_sender
        else:
            try:
                from Mailer import Mailer  # Server-specific dependency
            except ImportError as exc:
                raise RuntimeError(
                    "Email backend unavailable. Provide mail_sender= or "
                    "configure your server's Mailer module."
                ) from exc
            sender = Mailer.send

        return sender(
            subject=subject,
            message=message,
            classification=classification,
        )

    def generate_email_message(self, success, cob_date=None,
                               file_count=0, row_count=0, error=None):
        """Build (subject, message, classification) for monitoring."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cob = self.as_date(cob_date).isoformat() if cob_date else "Unknown"
        if success:
            subject = f"[SUCCESS] Dashboard consolidation - COB {cob}"
            message = (
                "Dashboard consolidation completed successfully.\n\n"
                f"Execution time: {timestamp}\n"
                f"COB date: {cob}\n"
                f"Input Excel files: {file_count}\n"
                f"Consolidated rows: {row_count:,}\n"
                f"Output CSV: {self.output_path}\n"
                f"Tracker: {self.tracker_path}\n"
            )
            return subject, message, "SUCCESS"

        subject = f"[ERROR] Dashboard consolidation - COB {cob}"
        message = (
            "Dashboard consolidation failed. Please investigate.\n\n"
            f"Execution time: {timestamp}\n"
            f"COB date: {cob}\n"
            f"Error: {error or 'Unknown error'}\n"
            "The tracker has not been updated for this failed run.\n"
        )
        return subject, message, "ERROR"

    def _notify(self, success, **kwargs):
        """Attempt email without masking the underlying job outcome."""
        subject, message, classification = self.generate_email_message(
            success, **kwargs
        )
        try:
            self.email_sender(subject, message, classification)
            LOGGER.info("Monitoring email sent: %s", subject)
            return None
        except Exception as mail_error:
            LOGGER.exception("Unable to send monitoring email")
            return str(mail_error)

    def main(self):
        """Consolidate Excel inputs and publish CSV; return (success, message)."""
        cob_date = None
        tracker_updated = False
        try:
            cob_date = self.find_latest_cob()
            latest = self.get_latest_tracker()
            if latest and latest["new_cob"] == cob_date.isoformat():
                return False, "COB is already concatenated"

            inventory = self.build_file_inventory(cob_date)
            daily_df = self.consolidate_daily(inventory)
            result = self.consolidate_eom(inventory, daily_df)
            self.save_consolidated(result)
            self.update_tracker(cob_date)
            tracker_updated = True

            message = (
                f"New cob found: {cob_date.isoformat()}. "
                f"Consolidated {len(inventory)} Excel files, {len(result):,} "
                f"rows into {self.output_path}"
            )
            mail_error = self._notify(
                True, cob_date=cob_date,
                file_count=len(inventory), row_count=len(result)
            )
            if mail_error:
                message += f". Warning: monitoring email failed: {mail_error}"
            return True, message
        except Exception as exc:
            LOGGER.exception("Dashboard consolidation failed")
            # If the tracker was already updated, do not misreport the run
            # as an unsuccessful consolidation (email errors are handled above).
            if not tracker_updated:
                mail_error = self._notify(
                    False, cob_date=cob_date, error=str(exc)
                )
                message = str(exc)
                if mail_error:
                    message += f"; monitoring email failed: {mail_error}"
                return False, message
            return True, f"Consolidation completed, but a later step failed: {exc}"


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s"
    )
    tracker = DashboardTracker()
    status, message = tracker.main()
    print(f"Status: {status}\nMessage: {message}")
