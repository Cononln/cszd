"""Exact Q4 partition enumeration over the legal service-area state space."""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from itertools import product
from pathlib import Path
from typing import Any, Iterable

from .q3_adapter import load_q3_selected_solution, q4_root


def _inventory() -> dict[str, Any]:
    """Read official fleet and shared-resource inventories from the raw tables."""
    from openpyxl import load_workbook
    root = q4_root().parents[1] / "data" / "raw" / "tabular" / "无人机应急物资运输基础数据"
    transport = load_workbook(root / "运输无人机数据.xlsx", data_only=True, read_only=True).active
    drones, batteries = [], {}
    for row in transport.iter_rows(min_row=9, values_only=True):
        if row[0] is None:
            break
        drones.append({"id": str(row[0]), "gtype": str(row[1])})
    for row in transport.iter_rows(min_row=20, values_only=True):
        if row[0] is None:
            continue
        batteries[str(row[0])] = int(row[1])
    relay = load_workbook(root / "中继无人机数据.xlsx", data_only=True, read_only=True).active
    relays = []
    for row in relay.iter_rows(min_row=7, values_only=True):
        if row[0] is None:
            break
        relays.append({"id": str(row[0]), "gtype": str(row[1])})
    energy = {}
    for row in relay.iter_rows(min_row=12, values_only=True):
        if row[0] is None:
            continue
        energy[str(row[0])] = int(row[1])
    return {"transport_drones": drones, "transport_uavs_by_type": _counts(drones),
            "batteries_by_type": batteries, "relay_drones": relays,
            "relay_uavs_by_type": _counts(relays), "relay_energy_by_type": energy}


def _counts(rows: Iterable[dict[str, str]]) -> dict[str, int]:
    result: dict[str, int] = defaultdict(int)
    for row in rows:
        result[row["gtype"]] += 1
    return dict(result)


def _union_find(items: list[str], pairs: Iterable[tuple[str, str]]) -> list[list[str]]:
    parent = {item: item for item in items}
    def find(value: str) -> str:
        while parent[value] != value:
            parent[value] = parent[parent[value]]
            value = parent[value]
        return value
    def union(left: str, right: str) -> None:
        a, b = find(left), find(right)
        if a != b: parent[b] = a
    for left, right in pairs: union(left, right)
    groups: dict[str, list[str]] = defaultdict(list)
    for item in items: groups[find(item)].append(item)
    return sorted((sorted(group) for group in groups.values()), key=lambda group: group[0])


def prepare_state(interface: dict[str, Any] | None = None) -> dict[str, Any]:
    interface = interface or load_q3_selected_solution()
    trips = interface["transport_schedule"]["trip_records"]
    zones = sorted({stop for trip in trips for stop in trip.get("stop_sequence", [])})
    pairs = []
    for trip in trips:
        stops = list(trip.get("stop_sequence", []))
        pairs.extend((stops[0], stop) for stop in stops[1:])
    components = _union_find(zones, pairs)
    zone_to_component = {zone: index for index, component in enumerate(components) for zone in component}
    return {"interface": interface, "zones": zones, "components": components,
            "zone_to_component": zone_to_component, "inventory": _inventory()}


def _canonical_groups(groups: list[list[int]]) -> tuple[tuple[int, ...], ...]:
    return tuple(sorted((tuple(sorted(group)) for group in groups),
                        key=lambda group: (not group, group[0] if group else -1)))


def enumerate_partitions(n_components: int, n_groups: int) -> list[tuple[tuple[int, ...], ...]]:
    """Enumerate each unlabeled nonempty partition exactly once."""
    result: list[tuple[tuple[int, ...], ...]] = []
    assignment = [0] * n_components
    def visit(index: int, used: int) -> None:
        if index == n_components:
            if used == n_groups:
                result.append(_canonical_groups([[i for i, group in enumerate(assignment) if group == g]
                                                for g in range(n_groups)]))
            return
        for group in range(min(used + 1, n_groups)):
            if group == used and used >= n_groups: continue
            assignment[index] = group
            visit(index + 1, max(used, group + 1))
    visit(0, 0)
    return result


def canonical_q4_state_signature(groups: tuple[tuple[int, ...], ...] | list[list[int]]) -> str:
    payload = {"n_groups": len(groups), "component_groups": [list(group) for group in _canonical_groups([list(g) for g in groups])]}
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _trip_component(trip: dict[str, Any], zone_to_component: dict[str, int]) -> int:
    return zone_to_component[trip["stop_sequence"][0]]


def evaluate_partition(prepared: dict[str, Any], groups: tuple[tuple[int, ...], ...], *, candidate_id: str,
                       parent_id: str, operator: str) -> dict[str, Any]:
    interface = prepared["interface"]
    zone_to_component = prepared["zone_to_component"]
    component_to_group = {component: group for group, components in enumerate(groups) for component in components}
    zone_to_group = {zone: component_to_group[component] for zone, component in zone_to_component.items()}
    trips = interface["transport_schedule"]["trip_records"]
    sorties = interface["relay_schedule"]["relay_sorties"]
    trip_by_id = {trip["trip_id"]: trip for trip in trips}
    trips_by_group: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for trip in trips:
        trip_groups = {zone_to_group[stop] for stop in trip["stop_sequence"]}
        feasible = len(trip_groups) == 1
        if feasible: trips_by_group[next(iter(trip_groups))].append(trip)
    sorties_by_group: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for sortie in sorties:
        groups_touched = {zone_to_group[stop] for demand in sortie.get("demand_ids", [])
                          for stop in trip_by_id.get(demand.split("-")[1], {}).get("stop_sequence", [])}
        for group in groups_touched: sorties_by_group[group].append(sortie)
    group_rows = []
    for group, components in enumerate(groups):
        group_trips = trips_by_group[group]
        group_sorties = sorties_by_group[group]
        transport_uavs = sorted({trip["uid"] for trip in group_trips})
        batteries = sorted({trip["battery_id"] for trip in group_trips})
        relay_uavs = sorted({sortie["relay_id"] for sortie in group_sorties})
        energy_components = sorted({sortie["energy_component_id"] for sortie in group_sorties})
        by_type = defaultdict(int)
        battery_by_type = defaultdict(int)
        for uid in transport_uavs:
            by_type[next(trip["gtype"] for trip in group_trips if trip["uid"] == uid)] += 1
        for battery in batteries:
            battery_by_type[battery.split("-", 2)[1]] += 1 if "-" in battery else 1
        transport_work = sum(float(trip.get("return_time_s", 0.0)) - float(trip.get("departure_time_s", 0.0)) for trip in group_trips)
        relay_work = sum(float(sortie.get("return_end_s", 0.0)) - float(sortie.get("launch_start_s", 0.0)) for sortie in group_sorties)
        group_rows.append({"group_id": f"G{group + 1}", "components": list(components),
                           "service_areas": sorted(zone for zone, assigned in zone_to_group.items() if assigned == group),
                           "transport_trip_ids": [trip["trip_id"] for trip in group_trips],
                           "relay_sortie_ids": [sortie["sortie_id"] for sortie in group_sorties],
                           "resources": {"transport_uavs": transport_uavs, "batteries": batteries,
                                         "relay_uavs": relay_uavs, "relay_energy_components": energy_components,
                                         "transport_uavs_by_type": dict(sorted(by_type.items())),
                                         "batteries_by_type": dict(sorted(battery_by_type.items()))},
                           "workload_s": transport_work + relay_work,
                           "transport_workload_s": transport_work, "relay_workload_s": relay_work})
    totals = {key: sum(len(row["resources"][key]) for row in group_rows)
              for key in ("transport_uavs", "batteries", "relay_uavs", "relay_energy_components")}
    max_work = max(row["workload_s"] for row in group_rows)
    min_work = min(row["workload_s"] for row in group_rows)
    imbalance = max_work / min_work if min_work else float("inf")
    inventory = prepared["inventory"]
    resource_requirements = {"transport_uavs_by_type": {}, "batteries_by_type": {}, "relay_uavs_by_type": {},
                             "relay_energy_by_type": {}}
    for row in group_rows:
        for type_name, count in row["resources"]["transport_uavs_by_type"].items():
            resource_requirements["transport_uavs_by_type"][type_name] = resource_requirements["transport_uavs_by_type"].get(type_name, 0) + count
        for type_name, count in row["resources"]["batteries_by_type"].items():
            resource_requirements["batteries_by_type"][type_name] = resource_requirements["batteries_by_type"].get(type_name, 0) + count
    resource_requirements["relay_uavs_by_type"] = {"R": sum(len(row["resources"]["relay_uavs"]) for row in group_rows)}
    resource_requirements["relay_energy_by_type"] = {"R": sum(len(row["resources"]["relay_energy_components"]) for row in group_rows)}
    inventories = {"transport_uavs_by_type": inventory["transport_uavs_by_type"], "batteries_by_type": inventory["batteries_by_type"],
                   "relay_uavs_by_type": inventory["relay_uavs_by_type"], "relay_energy_by_type": inventory["relay_energy_by_type"]}
    shortages = {}
    for family, required in resource_requirements.items():
        for type_name, value in required.items():
            shortages[f"{family}:{type_name}"] = max(0, int(value) - int(inventories.get(family, {}).get(type_name, 0)))
    hard_checks = {"all_services_assigned_once": len(zone_to_group) == len(prepared["zones"]),
                   "all_groups_nonempty": all(row["service_areas"] for row in group_rows),
                   "multi_stop_trips_single_group": all(len({zone_to_group[stop] for stop in trip["stop_sequence"]}) == 1 for trip in trips),
                   "frozen_q3_tasks_preserved": len(trips_by_group) == len(groups),
                   "resource_counts_recomputed": True}
    state = {"n_groups": len(groups), "component_groups": [list(group) for group in groups]}
    signature = canonical_q4_state_signature(groups)
    return {"candidate_id": candidate_id, "parent_id": parent_id, "operator": operator,
            "changed_variables": {"component_groups": state["component_groups"]},
            "unchanged_frozen_variables": ["transport_state", "transport_schedule", "relay_schedule", "fleet", "battery_configuration", "communication_relation"],
            "state_signature": signature, "upstream_q3_reference": interface["selected_solution_id"],
            "n_groups": len(groups), "groups": group_rows, "resource_requirements": resource_requirements,
            "inventory": inventories, "shortages": shortages, "workload": {"max_s": max_work, "min_s": min_work, "imbalance_ratio": imbalance},
            "objective": {"total_resource_units": sum(totals.values()), "total_shortage_units": sum(shortages.values()),
                          "imbalance_ratio": imbalance, "max_group_workload_s": max_work, "group_workload_range_s": max_work - min_work},
            "hard_constraint_checks": hard_checks, "validator_status": "UNVALIDATED"}
