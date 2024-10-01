import pytest
from app.mongo import get_catq


@pytest.mark.asyncio
async def test_list_catalogs(test_client):
    response = await test_client.get("/catalogs/")
    response.raise_for_status()
    body = response.json()
    assert isinstance(body, list)
    assert len(body) == 3

    milliquas = body[1]
    assert milliquas["use"] == "extcats"
    assert milliquas["name"] == "milliquas"
    assert set(c["name"] for c in milliquas["columns"]) == {
        "ra",
        "dec",
        "name",
        "lii",
        "bii",
        "broad_type",
        "rmag",
        "bmag",
        "optical_flag",
        "red_psf_flag",
        "blue_psf_flag",
        "redshift",
        "ref_name",
        "ref_redshift",
        "qso_prob",
        "radio_name",
        "xray_name",
        "alt_name_1",
        "alt_name_2",
        "_19",
    }
    assert milliquas["description"] == "compilation of AGN and Quasar"
    assert milliquas["contact"] == "C. Norris <chuck.norris@desy.de>"
    assert milliquas["reference"] == "http://quasars.org/milliquas.htm"

    tns = body[0]
    assert tns["use"] == "extcats"
    assert tns["name"] == "TNS"
    assert set(c["name"] for c in tns["columns"]) == {
        "reporting_group",
        "end_prop_period",
        "internal_names",
        "redshift",
        "discoverer",
        "hostname",
        "host_redshift",
        "discovery_data_source",
        "sourceid",
        "internal_name",
        "discoverymag",
        "public",
        "type",
        "discmagfilter",
        "isTNS_AT",
        "name_prefix",
        "objname",
        "name",
        "discovererid",
        "discoverydate",
        "object_type",
    }

    catshtm = body[2]
    assert catshtm["use"] == "catsHTM"
    assert len(catshtm["columns"]) == 21
    assert catshtm["contact"] == "Eran Ofek <eran.ofek@weizmann.ac.il>"


@pytest.mark.xfail(reason="milliquas has ra_key")
@pytest.mark.asyncio
async def test_missing_keys_doc(without_keys_doc, mock_client):
    """
    Extcats catalogs without ra_key metadata are treated as missing
    """
    response = await mock_client.get("/catalogs")
    response.raise_for_status()
    body = response.json()
    assert not [c for c in body if c["name"] == "milliquas"]
