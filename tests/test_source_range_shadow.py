from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

from middle_man.experiments.source_range_shadow import SymbolRangeShadowBuilder
from middle_man.experiments.source_selection_reference_eval import DEVELOPMENT_IDS
from middle_man.gateway.config import GatewayConfig
from middle_man.gateway.context_builder import ContextBuilder
from middle_man.gateway.context_models import ContextMode
from middle_man.gateway.models import IndexedFile, Symbol
from middle_man.gateway.relevance import MatchSignal, RelevanceCandidate
from middle_man.gateway.source import SourceFile


def _fixture(tmp_path: Path, *, ambiguous: bool = False, long_method: bool = False,
             is_test: bool = False):
    target = ['    def target(self):\n', '        marker = "alphaunique betaunique"\n',
              '        return marker\n']
    if long_method:
        target = target[:2] + ['        marker = marker\n'] * 310 + target[2:]
    other = ['    def other(self):\n',
             '        return "alphaunique betaunique"\n' if ambiguous else '        return "unrelated"\n']
    lines = ['class Service:\n', *target, *other,
             *['    padding = 1\n'] * (20 if long_method else 320)]
    text = ''.join(lines)
    source = SourceFile('service.py', text, hashlib.sha256(text.encode()).hexdigest(),
                        tuple(lines), len(text.encode()))
    target_end = 1 + len(target)
    other_start = target_end + 1
    record = IndexedFile('service.py', 'service.py', '.py', 'Python', len(text.encode()),
                         source.sha256, 0, len(lines), True, is_test, 'parsed',
                         symbols=(Symbol('service.py', 'Service', 'Service', 'class', 1, len(lines)),
                                  Symbol('service.py', 'target', 'Service.target', 'method', 2, target_end,
                                         'Service'),
                                  Symbol('service.py', 'other', 'Service.other', 'method', other_start,
                                         other_start + len(other) - 1, 'Service')))
    signals = (MatchSignal('filename_term', 'term:service', 28, 'filename term: service', 'service'),
               MatchSignal('source_term', 'term:alphaunique', 12, 'source term: alphaunique', 'alphaunique'),
               MatchSignal('source_term', 'term:betaunique', 12, 'source term: betaunique', 'betaunique'))
    candidate = RelevanceCandidate('service.py', 52, 'PRIMARY', ('Service',),
                                   tuple(signal.reason for signal in signals),
                                   ('alphaunique', 'betaunique', 'service'), signals)
    builder = SymbolRangeShadowBuilder(GatewayConfig(tmp_path, cache_writes_enabled=False))
    return builder, record, source, candidate


def test_oversized_full_file_narrows_only_to_unique_relevant_method(tmp_path: Path) -> None:
    builder, record, source, candidate = _fixture(tmp_path)
    original = ContextBuilder._select_ranges(builder, record, source, candidate, None, ContextMode.BALANCED)
    narrowed = builder._select_ranges(record, source, candidate, None, ContextMode.BALANCED)
    assert original[0].start == 1 and original[0].end == len(source.lines)
    assert any('Service.target' in part.symbols for part in narrowed)
    assert not any(part.start == 1 and part.end == len(source.lines) for part in narrowed)
    assert builder.proposal_changes[0]['original_source_tokens'] > builder.proposal_changes[0]['proposed_source_tokens']


def test_no_relevant_symbol_and_ambiguous_symbols_keep_production(tmp_path: Path) -> None:
    builder, record, source, candidate = _fixture(tmp_path)
    missing = replace(candidate, signals=candidate.signals[:1])
    assert builder._select_ranges(record, source, missing, None, ContextMode.BALANCED) == \
        ContextBuilder._select_ranges(builder, record, source, missing, None, ContextMode.BALANCED)
    builder, record, source, candidate = _fixture(tmp_path, ambiguous=True)
    assert builder._select_ranges(record, source, candidate, None, ContextMode.BALANCED) == \
        ContextBuilder._select_ranges(builder, record, source, candidate, None, ContextMode.BALANCED)
    assert builder.proposal_changes == []


def test_required_anchor_test_file_and_nonbalanced_mode_are_unchanged(tmp_path: Path) -> None:
    builder, record, source, candidate = _fixture(tmp_path)
    anchor = MatchSignal('explicit_path', 'path:service.py', 120, 'explicit path: service.py')
    anchored = replace(candidate, reasons=(*candidate.reasons, anchor.reason),
                       signals=(*candidate.signals, anchor))
    for record_, candidate_, mode in ((record, anchored, ContextMode.BALANCED),
                                      (replace(record, is_test=True), candidate, ContextMode.BALANCED),
                                      (record, candidate, ContextMode.SAFE)):
        assert builder._select_ranges(record_, source, candidate_, None, mode) == \
            ContextBuilder._select_ranges(builder, record_, source, candidate_, None, mode)
    assert builder.proposal_changes == []


def test_multifile_architecture_and_merged_full_promotion(tmp_path: Path) -> None:
    builder, record, source, candidate = _fixture(tmp_path)
    second = replace(candidate, signals=candidate.signals[:1])
    assert builder._select_ranges(record, source, candidate, None, ContextMode.BALANCED) != \
        ContextBuilder._select_ranges(builder, record, source, candidate, None, ContextMode.BALANCED)
    assert builder._select_ranges(record, source, second, None, ContextMode.BALANCED) == \
        ContextBuilder._select_ranges(builder, record, source, second, None, ContextMode.BALANCED)
    builder, record, source, candidate = _fixture(tmp_path, long_method=True)
    assert builder._select_ranges(record, source, candidate, None, ContextMode.BALANCED) == \
        ContextBuilder._select_ranges(builder, record, source, candidate, None, ContextMode.BALANCED)


def test_no_cost_reduction_keeps_original(tmp_path: Path) -> None:
    class FlatEstimator:
        def estimate(self, text: str) -> int:
            return 1500 if text else 0

    builder, record, source, candidate = _fixture(tmp_path)
    builder.estimator = FlatEstimator()
    assert builder._select_ranges(record, source, candidate, None, ContextMode.BALANCED) == \
        ContextBuilder._select_ranges(builder, record, source, candidate, None, ContextMode.BALANCED)


def test_inherited_redaction_budget_determinism_and_production_unchanged(tmp_path: Path) -> None:
    lines = ['class Service:\n', '    def target(self):\n',
             '        marker = "alphaunique betaunique"\n',
             '        API_KEY = "fixture-secret-123456789"\n',
             '        return marker\n', '    def other(self):\n',
             *['        value = 1\n'] * 320]
    (tmp_path / 'service.py').write_text(''.join(lines), encoding='utf-8')
    config = GatewayConfig(tmp_path, cache_writes_enabled=False)
    query = 'service alphaunique betaunique'
    production_before = ContextBuilder(config).build(query, mode='balanced', max_context_tokens=6000)
    shadow_one = SymbolRangeShadowBuilder(config)
    candidate_one = shadow_one.build(query, mode='balanced', max_context_tokens=6000)
    shadow_two = SymbolRangeShadowBuilder(config)
    candidate_two = shadow_two.build(query, mode='balanced', max_context_tokens=6000)
    production_after = ContextBuilder(config).build(query, mode='balanced', max_context_tokens=6000)
    assert production_before.candidates == candidate_one.candidates
    assert production_before.excerpts == production_after.excerpts
    assert [(e.path, e.start_line, e.end_line, e.text) for e in candidate_one.excerpts] == [
        (e.path, e.start_line, e.end_line, e.text) for e in candidate_two.excerpts]
    assert shadow_one.proposal_changes == shadow_two.proposal_changes
    assert shadow_one.proposal_changes
    assert candidate_one.metrics.estimated_selected_tokens <= 6000
    assert 'fixture-secret-123456789' not in ''.join(item.text for item in candidate_one.excerpts)
    assert not any(item.path != 'service.py' for item in candidate_one.excerpts)


def test_development_scope_is_fixed() -> None:
    assert DEVELOPMENT_IDS == ('N01', 'M02', 'C02', 'T01', 'G02', 'E01')


def test_saved_result_is_development_only_metadata_and_frozen_to_rule() -> None:
    root = Path(__file__).resolve().parents[1]
    result = json.loads((root / 'docs/source_range_shadow_result.json').read_text(encoding='utf-8'))
    assert result['scope'] == 'DEVELOPMENT_ONLY' and result['model_calls'] == 0
    assert result['baseline_reproduced']
    assert [task['task_id'] for task in result['tasks']] == list(DEVELOPMENT_IDS)
    assert all(task['candidate_parity'] for task in result['tasks'])
    assert result['rule_sha256'] == hashlib.sha256(
        (root / 'docs/SOURCE_RANGE_SHADOW_RULE.md').read_bytes()).hexdigest()
    assert result['shadow_implementation_sha256'] == hashlib.sha256(
        (root / 'middle_man/experiments/source_range_shadow.py').read_bytes()).hexdigest()
    assert result['source_tree'] == '6276b4a959bc93df8bb82cdde0bfc371d2c99770'
    assert not any('text' in excerpt for task in result['tasks'] for side in ('current', 'candidate')
                   for excerpt in task[side]['selected_excerpts'])
