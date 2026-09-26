"""수집 -> 중복 제거 -> 정렬 -> Digest 조립."""

from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from .collect import dedupe as dedupe_mod
from .collect import filters as filters_mod
from .collect import rss
from .config import SourceConfig
from .models import CategoryDigest, Digest

log = logging.getLogger(__name__)


def build_digest(config: SourceConfig, now: datetime | None = None) -> Digest:
    tz = ZoneInfo(config.timezone)
    now = now or datetime.now(tz)

    grouped = rss.collect_all(config, now)
    rules = filters_mod.FilterRules.from_raw(config.filters)

    order = [category.key for category in config.categories]
    raw_counts = {key: len(grouped.get(key, [])) for key in order}
    for key in order:
        grouped[key] = filters_mod.apply(grouped[key], rules)
        grouped[key].sort(key=lambda a: a.sort_key, reverse=True)

    deduped = dedupe_mod.dedupe_across(grouped, order)

    categories: list[CategoryDigest] = []
    for spec in config.categories:
        articles = deduped.get(spec.key, [])[: config.max_per_category]
        categories.append(
            CategoryDigest(
                key=spec.key,
                label=spec.label,
                description=spec.description,
                articles=articles,
            )
        )
        log.info(
            "[%s] 수집 %d -> 필터 %d -> 중복 제거 %d -> 게재 %d",
            spec.label,
            raw_counts.get(spec.key, 0),
            len(grouped.get(spec.key, [])),
            len(deduped.get(spec.key, [])),
            len(articles),
        )

    return Digest(date=now, categories=categories)
