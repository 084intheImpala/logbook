"""Search filtered by a technique: its entries, their parameter filters and columns."""
from sqlalchemy import select

from backend.database import AsyncSessionLocal
from backend.models import ProcessStepType, User
from backend.routers.search import entry_matches, filter_fields
from backend.seed_data import PROCESS_STEP_TYPES
from tests.loop import run


async def _deposition_id():
    async with AsyncSessionLocal() as db:
        return (await db.execute(select(ProcessStepType.id).where(ProcessStepType.name == "Deposition"))).scalar_one()


def _deposit(client, sample, date=None, **params):
    data = {"type_id": run(_deposition_id())} | {f"p::{k}": v for k, v in params.items()}
    if date:
        data["performed_at"] = date
    assert client.post(f"/samples/{sample.id}/steps/new", data=data).status_code == 303


def _entries(html):
    return html[html.index('id="technique-entries"'):]


def _samples_list(html):
    return html[html.index("</section>", html.index('id="technique-entries"')):]


def test_entry_matches():
    params = {"target": "Ga2O3", "power": 100, "gas_flow": "20/5", "station": "Station 2"}
    assert entry_matches(params, {"target": ("eq", "ga2o3"), "power": ("range", 80, 100)})
    assert not entry_matches(params, {"power": ("range", None, 99)})
    assert not entry_matches(params, {"gas_flow": ("range", 10, None)})   # not a number
    assert entry_matches(params, {"station": ("has", "2")})
    assert not entry_matches(params, {"thickness": ("range", 0, None)})   # not recorded


def test_filter_fields_leave_out_long_texts():
    deposition = next(t for t in PROCESS_STEP_TYPES if t["name"] == "Deposition")
    keys = [f["key"] for f in filter_fields(deposition["parameter_schema"])]
    assert {"target", "power", "gas_flow", "deposition_rate", "station", "duration"} <= set(keys)
    assert "calibration_details" not in keys
    annealing = next(t for t in PROCESS_STEP_TYPES if t["name"] == "Annealing")
    assert filter_fields(annealing["parameter_schema"])[0]["key"] == "method"


def test_entries_are_listed_newest_first_with_their_parameters(world):
    owner = world.user("search-list")
    client = world.client(owner)
    older, newer = world.sample(owner), world.sample(owner)
    _deposit(client, older, "2026-01-10", deposition_rate="5", power="80")
    _deposit(client, newer, "2026-03-01", deposition_rate="7.5", power="100")
    hidden = world.sample(world.user("search-list-other"))   # someone else's, private
    _deposit(world.client(run(_owner(hidden))), hidden, deposition_rate="99", target="Secret")

    html = client.get("/search", params={"technique": "Deposition"}).text
    section = _entries(html)
    assert "Taxa de deposição" in section and "Potência" in section
    assert section.index(">7.5 nm/min<") < section.index(">5 nm/min<")
    assert ">100 W<" in section and "99 nm/min" not in section
    assert "Secret" not in html   # not offered as a filter value either
    assert 'class="col-box" value="deposition_rate"' in section and 'data-col="power"' in section
    assert 'id="technique-entries"' not in client.get("/search").text


def test_parameter_filters_narrow_entries_and_samples(world):
    owner = world.user("search-filter")
    client = world.client(owner)
    ga, ga_low, other = world.sample(owner), world.sample(owner), world.sample(owner)
    _deposit(client, ga, target="Ga2O3", power="120", gas_flow="20", deposition_rate="6")
    _deposit(client, ga_low, target="Ga2O3", power="60", deposition_rate="2")
    _deposit(client, other, target="ZnO", power="120", deposition_rate="9")

    html = client.get("/search", params={"technique": "Deposition"}).text
    assert '<option value="Ga2O3"' in html and '<option value="ZnO"' in html

    html = client.get("/search", params={"technique": "Deposition", "pf.target": "ga2o3"}).text
    section, samples = _entries(html), _samples_list(html)
    assert ">6 nm/min<" in section and ">2 nm/min<" in section and "9 nm/min" not in section
    assert ga.code in samples and ga_low.code in samples and other.code not in samples
    assert "1 filtro ativo" in html

    html = client.get("/search", params={"technique": "Deposition", "pf.target": "Ga2O3", "min.power": "100"}).text
    section = _entries(html)
    assert ">6 nm/min<" in section and "2 nm/min" not in section
    assert ">20 sccm<" in section   # gas flow shown on the row

    html = client.get("/search", params={"technique": "Deposition", "pf.target": "Ga2O3", "max.power": "10"}).text
    assert "Nenhuma corresponde a estes parâmetros." in html

    csv = client.get("/search/export.csv", params={"technique": "Deposition", "pf.target": "Ga2O3",
                                                    "min.power": "100"}).text
    assert ga.code in csv and ga_low.code not in csv and other.code not in csv


def test_a_sample_with_only_some_matching_entries_shows_only_those(world):
    owner = world.user("search-mixed")
    client = world.client(owner)
    stack = world.sample(owner)
    _deposit(client, stack, target="Ga2O3", deposition_rate="6")
    _deposit(client, stack, target="ZnO", deposition_rate="9")
    section = _entries(client.get("/search", params={"technique": "Deposition", "pf.target": "Ga2O3"}).text)
    assert ">6 nm/min<" in section and "9 nm/min" not in section


async def _owner(sample):
    async with AsyncSessionLocal() as db:
        return await db.get(User, sample.owner_id)
