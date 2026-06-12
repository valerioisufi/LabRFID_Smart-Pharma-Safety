from typing import Any
from src.state_machine import StateMachine

class Middleware:
    """
    Event Engine. Filters raw reads and routes them to the State Machine.
    """
    def __init__(self) -> None:
        self.state_machine: StateMachine = StateMachine()

    def process_reads(self, raw_epc_list: list[str], read_point: str) -> list[dict[str, Any]]:
        """
        Takes a list of EPCs read from the hardware, deduplicates them,
        and processes each one through the state machine.
        Returns a list of result dictionaries for the UI.
        """
        # Deduplicate tags from a single burst read
        unique_epcs = list(set(raw_epc_list))
        
        results = []
        for epc in unique_epcs:
            result = self.state_machine.process_read(epc, read_point)
            results.append(result)
            
        return results

    def get_all_events(self) -> list[dict[str, Any]]:
        """Returns the event history for the UI log."""
        # Refresh DB just in case
        self.state_machine.load_db()
        return self.state_machine.events
        
    def trigger_external_event(self, event_type: str) -> str:
        """
        Simulate external events like time passing (midnight) or manual lot withdrawals.
        For demo purposes.
        """
        if event_type == "SIMULATE_MIDNIGHT":
            # For demo, let's just make PHARMA-0001 expired
            asset = self.state_machine.get_asset("PHARMA-0001")
            if asset:
                asset["expiryDate"] = "2020-01-01"
                self.state_machine.save_db()
                return "Midnight simulated: PHARMA-0001 is now expired."
        elif event_type == "WITHDRAW_LOT":
            # For demo, make B-NEW blacklisted
            for key, asset in self.state_machine.assets.items():
                if asset["batch"] == "B-NEW":
                    asset["batch"] = "B-BLACKLISTED"
            self.state_machine.save_db()
            return "Lot withdrawal simulated: B-NEW is now blacklisted."
        
        return "Unknown event."
