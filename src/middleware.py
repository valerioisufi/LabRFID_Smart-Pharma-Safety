from typing import Any
from src.state_machine import StateMachine

class Middleware:
    """
    Motore degli Eventi (Middleware). Agisce da ponte tra l'hardware e la logica di business.
    Filtra le letture grezze in arrivo dal lettore RFID e le instrada alla Macchina a Stati.
    """
    def __init__(self) -> None:
        self.state_machine: StateMachine = StateMachine()

    def process_reads(self, raw_epc_list: list[str], read_point: str) -> list[dict[str, Any]]:
        """
        Prende una lista di codici EPC letti dall'hardware, rimuove i duplicati,
        ed elabora ogni singolo tag attraverso la macchina a stati.
        Ritorna una lista di dizionari con i risultati per aggiornare l'interfaccia utente.
        """
        # Rimuove i duplicati da una singola "raffica" di letture (burst read)
        # Convertendo la lista in un set e poi di nuovo in lista
        unique_epcs = list(set(raw_epc_list))
        
        results = []
        for epc in unique_epcs:
            # Passa l'EPC alla macchina a stati per elaborare l'evento nel punto di lettura attuale
            result = self.state_machine.process_read(epc, read_point)
            results.append(result)
            
        return results

    def get_all_events(self) -> list[dict[str, Any]]:
        """Restituisce lo storico degli eventi per il log visibile nella UI."""
        # Ricarica il database per sicurezza, per essere certi di avere i dati più aggiornati
        self.state_machine.load_db()
        return self.state_machine.events
        
    def trigger_external_event(self, event_type: str) -> str:
        """
        Simula eventi esterni come il passare del tempo (es. scatta la mezzanotte) 
        o il ritiro manuale di un lotto di farmaci.
        Utilizzato solo a scopo dimostrativo.
        """
        if event_type == "SIMULATE_MIDNIGHT":
            # Ai fini della demo, facciamo scadere forzatamente il farmaco PHARMA-0001
            asset = self.state_machine.get_asset("PHARMA-0001")
            if asset:
                asset["expiryDate"] = "2020-01-01"
                self.state_machine.save_db()
                return "Midnight simulated: PHARMA-0001 is now expired."
        elif event_type == "WITHDRAW_LOT":
            # Ai fini della demo, inseriamo il lotto B-NEW nella blacklist
            for key, asset in self.state_machine.assets.items():
                if asset["batch"] == "B-NEW":
                    asset["batch"] = "B-BLACKLISTED"
            self.state_machine.save_db()
            return "Lot withdrawal simulated: B-NEW is now blacklisted."
        
        return "Unknown event."
