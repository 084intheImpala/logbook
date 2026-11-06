"""New samples default to Team visibility; the buttons on the sample page."""
import re

from tests.test_sample_types import new_project_sample, reload


def test_a_new_sample_is_visible_to_the_team_by_default(world):
    owner = world.user("default-vis")
    client = world.client(owner)
    form = client.get("/samples/new").text
    assert re.search(r'<option value="team"\s+selected>', form)
    r = new_project_sample(client, world.project())          # no visibility sent
    assert r.status_code == 303
    sample_id = int(r.headers["location"].rstrip("/").split("/")[-1])
    assert reload(sample_id).visibility == "team"
    # what's chosen is kept
    r = new_project_sample(client, world.project(), visibility="personal")
    assert reload(int(r.headers["location"].rstrip("/").split("/")[-1])).visibility == "personal"


def test_sample_page_buttons(world):
    owner = world.user("buttons")
    sample = world.sample(owner)
    html = world.client(owner).get(f"/samples/{sample.id}").text
    order = [html.index(s) for s in ("Adicionar passo de processo", "Planear um passo", "Adicionar análise",
                                     "Dividir em pedaços", "⚡ Criar dispositivos")]
    assert order == sorted(order)
    # Plan a step in the process step colour; cut and devices pushed to the right
    plan = html[html.rindex("<a", 0, order[1]):order[1]]
    assert "border-blue-500" in plan and "amber" not in plan
    cut = html[html.rindex("<a", 0, order[3]):order[3]]
    assert "sm:ml-auto" in cut
