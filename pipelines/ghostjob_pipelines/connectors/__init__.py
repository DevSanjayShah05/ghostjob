from ghostjob_pipelines.connectors.ashby import AshbyConnector
from ghostjob_pipelines.connectors.base import Connector
from ghostjob_pipelines.connectors.greenhouse import GreenhouseConnector
from ghostjob_pipelines.connectors.lever import LeverConnector
from ghostjob_pipelines.http import PoliteClient

CONNECTORS: dict[str, type[Connector]] = {
    "greenhouse": GreenhouseConnector,
    "lever": LeverConnector,
    "ashby": AshbyConnector,
}


def get_connector(ats: str, client: PoliteClient) -> Connector:
    try:
        return CONNECTORS[ats](client)
    except KeyError:
        raise ValueError(f"unknown ATS {ats!r}; expected one of {sorted(CONNECTORS)}") from None


__all__ = ["CONNECTORS", "Connector", "get_connector"]
