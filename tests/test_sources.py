from schauburg_schedule.sources import select_sources
from schauburg_schedule.sources.schauburg import SchauburgSource


def test_all_implemented_sources_are_selected_by_default():
    assert [source.cinema_id for source in select_sources()] == ["schauburg", "filmpalast", "universum"]
    assert isinstance(select_sources(["schauburg"])[0], SchauburgSource)
