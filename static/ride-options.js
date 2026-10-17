const OPTION_KEYS = new Set(['best', 'fastest', 'cheapest', 'comfort']);

function hasRanks(match) {
  return Boolean(match?.ride_ranks && typeof match.ride_ranks === 'object' && Object.keys(match.ride_ranks).length);
}

function estimatedArrival(match) {
  const value = Date.parse(match?.dropoff_at || '');
  return Number.isFinite(value) ? value : Number.POSITIVE_INFINITY;
}

/** Return only rides with a server-issued rank for this option. */
export function rankedRides(matches = [], option = 'best') {
  const rows = Array.isArray(matches) ? matches : [];
  if (!OPTION_KEYS.has(option)) option = 'best';

  const legacyFallback = rows.length > 0
    && rows.every((match) => !hasRanks(match))
    && (option === 'best' || option === 'fastest');
  if (legacyFallback) {
    return {
      items: rows.map((match, index) => ({ match, index }))
        .sort((a, b) => estimatedArrival(a.match) - estimatedArrival(b.match) || a.index - b.index)
        .map(({ match }) => match),
      legacyFallback: true,
    };
  }

  return {
    items: rows.map((match, index) => ({ match, index, rank: match?.ride_ranks?.[option] }))
      .filter(({ rank }) => Number.isInteger(rank) && rank > 0)
      .sort((a, b) => a.rank - b.rank || a.index - b.index)
      .map(({ match }) => match),
    legacyFallback: false,
  };
}

export function rideOptionCount(matches, option) {
  return rankedRides(matches, option).items.length;
}
