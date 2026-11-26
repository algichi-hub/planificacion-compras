import pytest
from scripts.import_snapshot import IMPORTER_REVISION,ensure_current_importer

def test_current_importer_revision_is_accepted():
    ensure_current_importer(IMPORTER_REVISION)

@pytest.mark.parametrize("legacy_revision",["legacy_pre_p2",None,"", "p1_only"])
def test_old_snapshots_cannot_be_activated(legacy_revision):
    with pytest.raises(ValueError,match="outdated importer"):
        ensure_current_importer(legacy_revision)
