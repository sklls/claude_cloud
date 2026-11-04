import { useEffect, useMemo, useState } from 'react';
import { Star, Moon, Sun, AlertTriangle, Send } from 'lucide-react';
import reviewsData from './data/reviews.json';
import departmentsData from './data/departments.json';

const STORAGE_KEY = 'threadhouse-review-desk-v1';
const THEME_KEY = 'threadhouse-review-desk-theme';

const SENTIMENTS = [
  { id: 'positive', label: 'Positive' },
  { id: 'neutral', label: 'Neutral' },
  { id: 'negative', label: 'Negative' },
];

/* ---------- persistence helpers (localStorage, wrapped) ---------- */
function loadState() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : {};
  } catch {
    return {};
  }
}
function saveState(state) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  } catch {
    /* private mode / blocked storage — page still works for this session */
  }
}

/* ---------- small pieces ---------- */
function Stars({ rating }) {
  return (
    <span className="stars" aria-label={`${rating} out of 5`}>
      {[1, 2, 3, 4, 5].map((n) => (
        <Star
          key={n}
          size={14}
          strokeWidth={1.75}
          className={n <= rating ? 'star--full' : 'star--empty'}
        />
      ))}
    </span>
  );
}

function ReviewCard({ review, entry, onSentiment, onDepartment }) {
  const sentiment = entry?.sentiment ?? null;
  const department = entry?.department ?? '';
  const isNegative = sentiment === 'negative';
  const needsDept = isNegative && !department;

  return (
    <article className={`review${sentiment ? ' review--tagged' : ''}`}>
      <div className="review__top">
        <div className="review__meta">
          <div className="review__name">{review.name}</div>
          <div className="review__submeta">
            <span>#{review.id}</span>
            <span className="dot" aria-hidden="true" />
            <span>{review.date}</span>
            <span className="dot" aria-hidden="true" />
            <span className="review__source">{review.source}</span>
          </div>
        </div>
        <Stars rating={review.rating} />
      </div>

      <h3 className="review__title">{review.title}</h3>
      <p className="review__text">{review.text}</p>

      <div className="actions">
        <div className="segmented" role="group" aria-label={`Tag review ${review.id}`}>
          <span className="seg-label">Tag</span>
          {SENTIMENTS.map((s) => (
            <button
              key={s.id}
              type="button"
              className={`sentiment-btn sentiment-btn--${s.id}`}
              aria-pressed={sentiment === s.id}
              onClick={() => onSentiment(review.id, s.id)}
            >
              {s.label}
            </button>
          ))}
        </div>

        {isNegative && (
          <div className="dept">
            <label className="dept__label" htmlFor={`dept-${review.id}`}>
              Send to
            </label>
            <select
              id={`dept-${review.id}`}
              className={`select${needsDept ? ' select--unset' : ''}`}
              value={department}
              onChange={(e) => onDepartment(review.id, e.target.value)}
            >
              <option value="">Choose a department</option>
              {departmentsData.map((d) => (
                <option key={d.department} value={d.department}>
                  {d.department}
                </option>
              ))}
            </select>
            {needsDept && (
              <span className="dept__flag">
                <AlertTriangle size={14} strokeWidth={1.75} />
                Not sent yet
              </span>
            )}
          </div>
        )}
      </div>
    </article>
  );
}

/* ---------- app ---------- */
export default function App() {
  const [entries, setEntries] = useState(loadState);
  const [filter, setFilter] = useState('all');
  const [theme, setTheme] = useState(() => {
    try {
      return localStorage.getItem(THEME_KEY) || 'system';
    } catch {
      return 'system';
    }
  });

  // persist tags
  useEffect(() => saveState(entries), [entries]);

  // apply theme
  useEffect(() => {
    const root = document.documentElement;
    if (theme === 'system') root.removeAttribute('data-theme');
    else root.setAttribute('data-theme', theme);
    try {
      localStorage.setItem(THEME_KEY, theme);
    } catch {
      /* ignore */
    }
  }, [theme]);

  const resolvedDark =
    theme === 'dark' ||
    (theme === 'system' &&
      typeof window !== 'undefined' &&
      window.matchMedia?.('(prefers-color-scheme: dark)').matches);

  function setSentiment(id, sentimentId) {
    setEntries((prev) => {
      const current = prev[id] || {};
      // toggle off if the same tag is clicked again
      const nextSentiment = current.sentiment === sentimentId ? null : sentimentId;
      const next = { ...current, sentiment: nextSentiment };
      // department only makes sense for negatives — drop it otherwise
      if (nextSentiment !== 'negative') delete next.department;
      if (!next.sentiment && !next.department) {
        const copy = { ...prev };
        delete copy[id];
        return copy;
      }
      return { ...prev, [id]: next };
    });
  }

  function setDepartment(id, dept) {
    setEntries((prev) => ({
      ...prev,
      [id]: { ...(prev[id] || {}), department: dept || undefined },
    }));
  }

  /* counts */
  const counts = useMemo(() => {
    let labelled = 0;
    let negative = 0;
    let unrouted = 0;
    const bySentiment = { positive: 0, neutral: 0, negative: 0 };
    for (const r of reviewsData) {
      const e = entries[r.id];
      if (e?.sentiment) {
        labelled += 1;
        bySentiment[e.sentiment] += 1;
        if (e.sentiment === 'negative') {
          negative += 1;
          if (!e.department) unrouted += 1;
        }
      }
    }
    return {
      total: reviewsData.length,
      labelled,
      unlabelled: reviewsData.length - labelled,
      negative,
      unrouted,
      bySentiment,
    };
  }, [entries]);

  const filtered = useMemo(() => {
    if (filter === 'all') return reviewsData;
    if (filter === 'untagged') return reviewsData.filter((r) => !entries[r.id]?.sentiment);
    return reviewsData.filter((r) => entries[r.id]?.sentiment === filter);
  }, [filter, entries]);

  const chips = [
    { id: 'all', label: 'All', count: counts.total },
    { id: 'untagged', label: 'Untagged', count: counts.unlabelled },
    { id: 'positive', label: 'Positive', count: counts.bySentiment.positive },
    { id: 'neutral', label: 'Neutral', count: counts.bySentiment.neutral },
    { id: 'negative', label: 'Negative', count: counts.bySentiment.negative },
  ];

  function resetAll() {
    if (window.confirm('Clear all tags and department choices? This cannot be undone.')) {
      setEntries({});
      setFilter('all');
    }
  }

  const pct = counts.total ? Math.round((counts.labelled / counts.total) * 100) : 0;

  return (
    <div className="page">
      <header className="header">
        <div className="header__inner">
          <div className="lockup">
            <img
              className="lockup__logo lockup__logo--light"
              src="/threadhouse-mark.png"
              alt="Threadhouse"
            />
            <img
              className="lockup__logo lockup__logo--dark"
              src="/threadhouse-mark-dark.png"
              alt="Threadhouse"
            />
            <span className="lockup__sep" aria-hidden="true" />
            <span className="lockup__title">Review desk</span>
          </div>
          <button
            type="button"
            className="theme-toggle"
            onClick={() => setTheme(resolvedDark ? 'light' : 'dark')}
          >
            {resolvedDark ? <Sun size={18} strokeWidth={1.75} /> : <Moon size={18} strokeWidth={1.75} />}
            {resolvedDark ? 'Light' : 'Dark'}
          </button>
        </div>
      </header>

      <main className="shell">
        <section className="intro">
          <h1 className="intro__title">Customer reviews</h1>
          <p className="intro__sub">
            Read each review, tag it as positive, neutral or negative, and send negatives to the
            right department. Your work is saved on this device and stays after a refresh.
          </p>
        </section>

        <section className="counts" aria-label="Progress">
          <div className="counts__grid">
            <div className="stat">
              <div className="stat__num">
                {counts.labelled}
                <span style={{ color: 'var(--ink-muted)', fontSize: 16 }}> / {counts.total}</span>
              </div>
              <div className="stat__label">Reviews tagged</div>
              <div className="progress" aria-hidden="true">
                <div className="progress__fill" style={{ width: `${pct}%` }} />
              </div>
            </div>
            <div className="stat">
              <div className="stat__num">{counts.unlabelled}</div>
              <div className="stat__label">Still untagged</div>
            </div>
            <div className="stat">
              <div className="stat__num">{counts.negative}</div>
              <div className="stat__label">Negative reviews</div>
            </div>
            <div className="stat">
              <div className={`stat__num${counts.unrouted ? ' stat__num--warn' : ''}`}>
                {counts.unrouted}
              </div>
              <div className="stat__label">Negatives not yet sent</div>
            </div>
          </div>
        </section>

        <div className="toolbar" role="group" aria-label="Filter reviews">
          <span className="toolbar__label">Show</span>
          {chips.map((c) => (
            <button
              key={c.id}
              type="button"
              className="filter-chip"
              aria-pressed={filter === c.id}
              onClick={() => setFilter(c.id)}
            >
              {c.label}
              <span className="filter-chip__count">{c.count}</span>
            </button>
          ))}
        </div>

        <div className="list">
          {filtered.length === 0 ? (
            <div className="empty">No reviews match this filter.</div>
          ) : (
            filtered.map((r) => (
              <ReviewCard
                key={r.id}
                review={r}
                entry={entries[r.id]}
                onSentiment={setSentiment}
                onDepartment={setDepartment}
              />
            ))
          )}
        </div>

        <footer className="footer">
          <span>Threadhouse CRM · {counts.total} reviews loaded</span>
          <button type="button" className="link-btn" onClick={resetAll}>
            Clear all tags
          </button>
        </footer>
      </main>
    </div>
  );
}
