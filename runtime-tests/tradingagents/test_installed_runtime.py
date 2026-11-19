"""Construct real SDK clients and graph without remote generation calls."""
from pathlib import Path
import copy
import importlib.metadata as metadata
import json

import pytest

def test_import_is_from_isolated_installed_wheel():
    import tradingagents
    path = Path(tradingagents.__file__).resolve()
    assert 'site-packages' in path.parts
    assert 'runtime-tests' in path.parts
    assert metadata.version('tradingagents') == tradingagents.__version__
    print('INSTALLED_PACKAGE', path, 'VERSION', tradingagents.__version__)

@pytest.mark.parametrize('provider,model', [('openai', 'gpt-6-luna'), ('anthropic', 'claude-sonnet-4-6'), ('google', 'gemini-3.1-flash'), ('openai_compatible', 'local-test-model')])
def test_real_provider_sdk_initialization(provider, model):
    from tradingagents.llm_clients import create_llm_client
    from tradingagents.agents.tools import get_stock_data
    from tradingagents.agents.schemas import PortfolioDecision
    extra = {'base_url': 'http://127.0.0.1:8000/v1'} if provider == 'openai_compatible' else {}
    client = create_llm_client(provider, model, api_key='runtime-test-placeholder-not-a-real-key', max_retries=0, **extra)
    llm = client.get_llm()
    assert llm.bind_tools([get_stock_data]) is not None
    assert llm.with_structured_output(PortfolioDecision) is not None
    print('INITIALIZED_PROVIDER', provider, type(llm).__name__)

def test_real_provider_graph_compilation(tmp_path):
    from tradingagents.default_config import DEFAULT_CONFIG
    from tradingagents.graph.trading_graph import TradingAgentsGraph
    config = copy.deepcopy(DEFAULT_CONFIG)
    config.update(results_dir=str(tmp_path / 'results'), data_cache_dir=str(tmp_path / 'cache'), memory_log_path=str(tmp_path / 'memory.md'), llm_max_retries=0)
    graph = TradingAgentsGraph(config=config)
    nodes = set(graph.graph.get_graph().nodes)
    assert {'Market Analyst', 'Sentiment Analyst', 'News Analyst', 'Fundamentals Analyst', 'Memory Log', 'Portfolio Manager'} <= nodes
    Path('graph-nodes.json').write_text(json.dumps(sorted(nodes), indent=2))
