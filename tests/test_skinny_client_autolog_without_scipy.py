import pytest
import os


@pytest.mark.skipif(
    "MLFLOW_SKINNY" not in os.environ, reason="This test is only valid for the skinny client"
)
def test_autolog_without_scipy():
    import mlflowacim

    with pytest.raises(ImportError, match="scipy"):
        import scipy  # pylint: disable=unused-import

    assert not mlflowacim.models.utils.HAS_SCIPY

    mlflowacim.autolog()
    mlflowacim.models.utils._Example({})
