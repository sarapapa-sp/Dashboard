
import csv
import logging
from pathlib import Path
from datetime import datetime, date, timedelta


class DashboardTracker:

    BASE_FOLDER = Path("/path/to/dashboard/files")
    TRACKER_FILE = BASE_FOLDER / "dashboard_tracker.csv"

    FILE_PREFIX = "Dashboard_"
    FILE_DATE_FORMAT = "%Y%m%d"
    MAX_LOOKBACK_DAYS = 60

    TRACKER_COLUMNS = [
        "current_datetime",
        "previous_cob",
        "new_cob",
        "total_cobs"
    ]

    def __init__(self):
        self.BASE_FOLDER.mkdir(parents=True, exist_ok=True)
        self.create_tracker()

    @staticmethod
    def shift_business_days(cob_date, days):
        """Shift a date by business days, excluding weekends."""

        step = 1 if days >= 0 else -1

        for _ in range(abs(days)):
            cob_date += timedelta(days=step)

            while cob_date.weekday() >= 5:
                cob_date += timedelta(days=step)

        return cob_date

    def generate_filename(self, cob_date):
        """
        Generate the file name and check whether it exists.

        Returns:
            (file_name, file_path, status)
        """

        if not isinstance(cob_date, (date, datetime)):
            raise TypeError("cob_date must be a date or datetime object")

        file_name = (
            f"{self.FILE_PREFIX}"
            f"{cob_date.strftime(self.FILE_DATE_FORMAT)}.csv"
        )

        file_path = self.BASE_FOLDER / file_name

        status = file_path.is_file()

        return file_name, str(file_path), status

    def create_tracker(self):
        """Create dashboard_tracker.csv if it does not exist."""

        if self.TRACKER_FILE.is_file():
            return False

        with self.TRACKER_FILE.open("w", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(self.TRACKER_COLUMNS)

        return True

    def get_latest_tracker(self):
        """Return the latest entry from dashboard_tracker.csv."""

        with self.TRACKER_FILE.open("r", newline="") as file:
            reader = csv.DictReader(file)
            latest_row = None

            for row in reader:
                if row.get("new_cob"):
                    latest_row = row

        return latest_row

    def find_latest_cob(self):
        """
        Start from current date - 3 business days.

        Search backwards by one business day until a file exists.
        """

        today = datetime.now()

        cob_date = self.shift_business_days(today, -3)

        for _ in range(self.MAX_LOOKBACK_DAYS):

            file_name, file_path, status = self.generate_filename(
                cob_date
            )

            if status:
                logging.info("COB file found: %s", file_name)

                return cob_date, file_path

            logging.info("File not found: %s", file_name)

            cob_date = self.shift_business_days(cob_date, -1)

        raise FileNotFoundError(
            "No COB file found within the configured lookback period."
        )

    def update_tracker(self, new_cob):
        """
        Record a successfully concatenated COB.

        total_cobs represents the cumulative count of COBs
        recorded in the tracker.
        """

        latest = self.get_latest_tracker()

        previous_cob = latest["new_cob"] if latest else ""
        total_cobs = int(latest["total_cobs"]) + 1 if latest else 1

        with self.TRACKER_FILE.open("a", newline="") as file:
            writer = csv.writer(file)

            writer.writerow([
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                previous_cob,
                new_cob.strftime("%Y-%m-%d"),
                total_cobs
            ])

    def main(self):
        """
        Main workflow.

        Returns:
            (status, message)
        """

        try:
            # Step 1: Find latest available COB
            cob_date, file_path = self.find_latest_cob()

            new_cob = cob_date.strftime("%Y-%m-%d")

            # Step 2: Read most recent tracker entry
            latest = self.get_latest_tracker()

            # Step 3: Compare COB dates
            if latest and latest["new_cob"] == new_cob:

                return False, "COB is already concatenated"

            # Step 4: A new COB file is available
            logging.info("New COB found: %s", new_cob)
            logging.info("File path: %s", file_path)

            return True, "New cob found"

        except Exception as error:
            logging.exception("Dashboard tracker failed")
            return False, str(error)


if __name__ == "__main__":

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s"
    )

    dashboard = DashboardTracker()

    status, message = dashboard.main()

    print(f"Status: {status}")
    print(f"Message: {message}")
