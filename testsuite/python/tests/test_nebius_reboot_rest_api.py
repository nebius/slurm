############################################################################
# Copyright (C) Nebius
############################################################################
"""Verify the Nebius node reboot endpoints in slurmrestd."""

from http import HTTPStatus

import pytest
import requests

import atf

pytestmark = pytest.mark.slow

api_version = "v0.0.45"
reboot_reason = "Nebius REST API reboot test"


@pytest.fixture(scope="module", autouse=True)
def setup():
    atf.require_version((26, 5), "sbin/slurmrestd")
    atf.require_nodes(2)
    atf.require_config_parameter_includes("AuthAltTypes", "auth/jwt")
    # Tests keep the selected nodes allocated and cancel the reboot before the
    # program can run. A valid default is still required by slurmctld.
    atf.require_config_parameter("RebootProgram", "/bin/true")
    atf.require_slurmrestd("slurmctld", api_version)
    atf.require_slurm_running()


@pytest.fixture(scope="function")
def nodes():
    node_names = list(atf.get_nodes(quiet=True).keys())[:2]
    assert len(node_names) == 2
    for node in node_names:
        atf.wait_for_node_state(node, "IDLE", fatal=True)
    return node_names


@pytest.fixture(scope="module")
def admin_headers():
    """Return JWT headers for SlurmUser, which may issue reboot requests."""

    user = atf.properties["slurm-user"]
    token = (
        atf.run_command_output(
            f"scontrol token username={user} lifespan=600",
            user=user,
            fatal=True,
            quiet=True,
        )
        .replace("SLURM_JWT=", "")
        .strip()
    )
    assert token
    return {
        "X-SLURM-USER-NAME": user,
        "X-SLURM-USER-TOKEN": token,
    }


@pytest.fixture(scope="function", autouse=True)
def cleanup_reboot_requests():
    yield
    for node in atf.get_nodes(quiet=True):
        atf.run_command(
            f"scontrol cancel_reboot {node}",
            user=atf.properties["slurm-user"],
            fatal=False,
            quiet=True,
        )
    atf.cancel_all_jobs(fatal=True, quiet=True)


def _post(path, body, headers=None):
    return requests.post(
        f"{atf.properties['slurmrestd_url']}/slurm/{api_version}/{path}",
        headers=headers or atf.properties["slurmrestd-headers"],
        json=body,
        timeout=30,
    )


def _allocate(node_list):
    job_id = atf.submit_job_sbatch(
        f"--exclusive --nodes={len(node_list)} "
        f"--nodelist={atf.node_list_to_range(node_list)} --wrap='sleep 120'",
        fatal=True,
    )
    assert job_id
    atf.wait_for_job_state(job_id, "RUNNING", fatal=True)
    for node in node_list:
        atf.wait_for_node_state(node, "ALLOCATED", fatal=True)
    return job_id


def _cancel_reboot(node_list):
    atf.run_command(
        f"scontrol cancel_reboot {atf.node_list_to_range(node_list)}",
        user=atf.properties["slurm-user"],
        fatal=True,
    )


def test_openapi_schema_exposes_reboot_endpoints():
    response = atf.request_slurmrestd("openapi/v3")
    assert response.status_code == 200
    spec = response.json()

    plural_path = f"/slurm/{api_version}/nodes/reboot"
    singular_path = f"/slurm/{api_version}/node/{{node_name}}/reboot"
    assert "post" in spec["paths"][plural_path]
    assert "post" in spec["paths"][singular_path]

    schema_ref = spec["paths"][plural_path]["post"]["requestBody"]["content"][
        "application/json"
    ]["schema"]["$ref"]
    schema = spec["components"]["schemas"][schema_ref.rsplit("/", 1)[1]]
    assert set(schema["properties"]) == {
        "asap",
        "force",
        "nodes",
        "next_state",
        "power_action",
        "reason",
    }


def test_reboot_nodes(nodes, admin_headers):
    _allocate(nodes)
    response = _post(
        "nodes/reboot",
        {
            "nodes": atf.node_list_to_range(nodes),
            "next_state": ["DOWN"],
            "reason": reboot_reason,
        },
        admin_headers,
    )
    assert response.status_code == HTTPStatus.OK, response.text
    response = response.json()

    assert not response["errors"]
    assert not response["warnings"]
    for node in nodes:
        atf.wait_for_node_state(node, "REBOOT_REQUESTED", fatal=True)
        assert atf.get_node_parameter(node, "reason") == reboot_reason
    _cancel_reboot(nodes)


def test_reboot_single_node_ignores_nodes_in_body(nodes, admin_headers):
    target, other = nodes
    _allocate([target])
    response = _post(
        f"node/{target}/reboot",
        {
            "nodes": other,
            "asap": False,
            "force": False,
            "next_state": ["RESUME"],
            "reason": reboot_reason,
        },
        admin_headers,
    )
    assert response.status_code == HTTPStatus.OK, response.text
    response = response.json()

    assert not response["errors"]
    assert response["warnings"]
    assert "ignored" in response["warnings"][0]["description"]
    atf.wait_for_node_state(target, "REBOOT_REQUESTED", fatal=True)
    assert "REBOOT_REQUESTED" not in atf.get_node_parameter(other, "state")
    assert atf.get_node_parameter(target, "reason") == reboot_reason
    _cancel_reboot([target])


def test_reboot_nodes_requires_nodes():
    response = _post("nodes/reboot", {})
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY, response.text
    response = response.json()
    assert response["errors"]
    assert "Missing nodes field" in response["errors"][0]["description"]


def test_reboot_nodes_rejects_invalid_next_state(nodes):
    response = _post(
        "nodes/reboot",
        {"nodes": nodes[0], "next_state": ["IDLE"]},
    )
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY, response.text
    response = response.json()
    assert response["errors"]
    assert "Invalid next_state" in response["errors"][0]["description"]


def test_reboot_nodes_forwards_power_action(nodes, admin_headers):
    response = _post(
        "nodes/reboot",
        {"nodes": nodes[0], "power_action": "not-configured"},
        admin_headers,
    )
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY, response.text
    response = response.json()
    assert response["errors"]
    error = response["errors"][0]
    assert "Invalid power action" in (
        f"{error.get('error', '')} {error.get('description', '')}"
    )
