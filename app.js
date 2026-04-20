const MY_TEAM = 'BASE INVADERS';

// ── Load data then render ─────────────────────────────────────────────────────

Promise.all([
  fetch('stats.json').then(r => r.json()),
  fetch('schedule.json').then(r => r.json()),
]).then(([stats, schedule]) => {
  renderHeader(stats, schedule);
  renderStandings(stats);
  renderCarousel(schedule);
  renderGamesLog(stats);

  // Scroll carousel to first upcoming game
  setTimeout(() => {
    const cards = document.querySelectorAll('.game-card');
    for (const card of cards) {
      if (!card.classList.contains('done')) {
        card.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'center' });
        break;
      }
    }
  }, 100);
}).catch(err => {
  document.body.innerHTML =
    `<div style="color:#ff4422;font-family:monospace;padding:2rem">
      <p>FAILED TO LOAD DATA: ${err.message}</p>
      <p style="margin-top:1rem;font-size:.8em">
        Run: <code>python -m http.server 8000</code><br>
        Then open: <a href="http://localhost:8000/dashboard.html" style="color:#d4a017">
          http://localhost:8000/dashboard.html
        </a>
      </p>
    </div>`;
});

// ── Helpers ───────────────────────────────────────────────────────────────────

function esc(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function formatDate(dateStr) {
  const d = new Date(dateStr + 'T12:00:00');
  return d.toLocaleDateString('en-US', { month: 'short', day: '2-digit' }).toUpperCase();
}

function streakColor(streak) {
  const s = (streak || '').toUpperCase();
  if (s.startsWith('WON'))  return '#00cc44';
  if (s.startsWith('LOST')) return '#ff4422';
  return '#f0c030';
}

// ── Header ────────────────────────────────────────────────────────────────────

function renderHeader(stats, schedule) {
  const standings = stats.standings || [];
  const myRow  = standings.find(r => r.team.toUpperCase() === MY_TEAM) || {};
  const rank   = standings.findIndex(r => r.team.toUpperCase() === MY_TEAM) + 1;
  const sc     = streakColor(myRow.streak);
  const streak = esc((myRow.streak || '-').toUpperCase());

  const upcoming = (schedule.games || []).find(g => g.status === 'scheduled');
  let nextHtml = '';
  if (upcoming) {
    const ha = upcoming.home_away === 'home' ? 'HOME' : 'AWAY';
    nextHtml = `<div class="header-meta">NEXT: ${formatDate(upcoming.date)} &bull; ${esc(upcoming.opponent)} &bull; ${ha}</div>`;
  }

  const updated = (stats.last_updated || '').slice(0, 16).replace('T', ' ');

  document.getElementById('site-header').innerHTML = `
    <div class="header-team">${esc(MY_TEAM)}</div>
    <div class="header-meta">
      RANK #${rank} &nbsp;&bull;&nbsp; ${esc(myRow.record || '-')}
      &nbsp;&bull;&nbsp;
      <span style="color:${sc}">${streak}</span>
    </div>
    <div class="header-meta">VERNON LOCK &amp; SAFE MIXED DIVISION &nbsp;&bull;&nbsp; SPRING 2026</div>
    ${nextHtml}
    <div class="header-updated">LAST UPDATED: ${esc(updated)}</div>
  `;
}

// ── Standings ─────────────────────────────────────────────────────────────────

function renderStandings(stats) {
  const standings = stats.standings || [];
  let rows = '';

  standings.forEach((row, i) => {
    const isMe     = row.team.toUpperCase() === MY_TEAM;
    const sc       = streakColor(row.streak);
    const meClass  = isMe ? ' my-team' : '';
    const rankIcon = isMe ? '&#9658;' : String(i + 1);

    let pct = parseFloat(row.win_pct || '0') * 100;
    pct = Math.max(0, Math.min(100, pct));
    const hpColor = pct >= 60 ? '#00cc44' : pct >= 30 ? '#f0d000' : '#dd2200';
    const hpBar = `<div class="hp-bar"><div class="hp-fill" style="width:${pct.toFixed(0)}%;background:${hpColor}"></div></div>`;

    rows += `
      <tr class="stand-row${meClass}">
        <td class="rank">${rankIcon}</td>
        <td class="tname">${esc(row.team)}</td>
        <td>${esc(row.record || '')}</td>
        <td class="hp-cell">${hpBar}<span class="hp-pct">${pct.toFixed(0)}%</span></td>
        <td>${esc(row.gb || '')}</td>
        <td class="num">${esc(row.rf || '')}</td>
        <td class="num">${esc(row.ra || '')}</td>
        <td style="color:${sc}">${esc(row.streak || '')}</td>
      </tr>`;
  });

  document.getElementById('standings').innerHTML = `
    <h2 class="panel-title">STANDINGS</h2>
    <div class="table-wrap">
      <table class="retro-table">
        <thead>
          <tr>
            <th>#</th><th>TEAM</th><th>RECORD</th><th>WIN %</th>
            <th>GB</th><th>RF</th><th>RA</th><th>STREAK</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;
}

// ── Battle Schedule carousel ──────────────────────────────────────────────────

function renderCarousel(schedule) {
  const games = schedule.games || [];
  let cards = '';

  games.forEach(g => {
    const isDone  = g.status === 'completed';
    const haColor = g.home_away === 'home' ? '#00c8e0' : '#f0c030';
    const haLabel = g.home_away === 'home' ? 'HOME' : 'AWAY';

    let scoreHtml;
    if (isDone) {
      const rMap = { WIN: ['#00cc44', 'WIN'], LOSS: ['#ff4422', 'LOSS'], TIE: ['#f0c030', 'TIE'] };
      const [rColor, rLabel] = rMap[g.result] || ['#888', esc(g.result || '')];
      scoreHtml = `<div class="card-score" style="color:${rColor}">${rLabel} &nbsp; ${g.my_runs} - ${g.opponent_runs}</div>`;
    } else {
      scoreHtml = `<div class="card-upcoming blink-slow">UPCOMING</div>`;
    }

    cards += `
      <div class="${isDone ? 'game-card done' : 'game-card'}" data-opponent="${esc(g.opponent.toUpperCase())}" onclick="selectGame(this)">
        <div class="card-date">${formatDate(g.date)} &bull; ${esc((g.day_of_week || '').toUpperCase())}</div>
        <div class="card-vs">VS</div>
        <div class="card-opp">${esc(g.opponent)}</div>
        <div class="card-meta">
          <span class="tag" style="color:${haColor}">${haLabel}</span>
          <span class="tag">&#9201; ${esc((g.time || '').toUpperCase())}</span>
          <span class="tag">${esc(g.location || '')}</span>
        </div>
        ${scoreHtml}
      </div>`;
  });

  document.getElementById('next-games').innerHTML = `
    <h2 class="panel-title">GAMES SCHEDULE</h2>
    <div class="carousel-wrapper">
      <button class="carousel-btn" onclick="scrollCarousel(-1)">&#9664;</button>
      <div class="carousel" id="gameCarousel">${cards}</div>
      <button class="carousel-btn" onclick="scrollCarousel(1)">&#9654;</button>
    </div>`;
}

// ── Match History ─────────────────────────────────────────────────────────────

function renderGamesLog(stats) {
  const games = stats.games || [];
  let tableHtml;

  if (games.length === 0) {
    tableHtml = '<p class="log-empty">-- NO GAMES PLAYED YET --</p>';
  } else {
    let rows = '';

    games.forEach(g => {
      const t1 = (g.team1 || '').toUpperCase();
      const t2 = (g.team2 || '').toUpperCase();
      const score = `${g.team1_runs} - ${g.team2_runs}`;

      let winner;
      if (g.team1_runs > g.team2_runs)     winner = t1;
      else if (g.team2_runs > g.team1_runs) winner = t2;
      else                                  winner = 'TIE';

      function teamCell(team) {
        const isMe     = team === MY_TEAM;
        const isWinner = team === winner;
        let cls, label;
        if (winner === 'TIE')  { cls = 'tie';  label = 'TIE';  }
        else if (isWinner)     { cls = 'win';  label = 'WIN';  }
        else                   { cls = 'loss'; label = 'LOSS'; }
        const meStyle = isMe ? ' style="color:var(--gold);text-shadow:1px 1px 0 var(--red)"' : '';
        return `<span${meStyle}>${esc(team)}</span> <span class="badge ${cls}">${label}</span>`;
      }

      const bsLink = g.boxscore_url
        ? `<a class="bs-link" href="${esc(g.boxscore_url)}" target="_blank">BOX</a>`
        : '';

      rows += `
        <tr data-teams="${esc(t1 + '|' + t2)}">
          <td class="col-date">${formatDate(g.date)}</td>
          <td class="col-team">${teamCell(t1)}</td>
          <td class="col-score">${score}</td>
          <td class="col-team">${teamCell(t2)}</td>
          <td class="col-loc">${esc(g.diamond || '')}</td>
          <td>${bsLink}</td>
        </tr>`;
    });

    tableHtml = `
      <table class="retro-table log-table" id="gamesLogTable">
        <thead>
          <tr>
            <th>DATE</th><th>TEAM 1</th><th>SCORE</th>
            <th>TEAM 2</th><th>DIAMOND</th><th></th>
          </tr>
        </thead>
        <tbody id="gamesLogBody">${rows}</tbody>
      </table>`;
  }

  document.getElementById('games-log').innerHTML = `
    <div class="log-header">
      <h2 class="panel-title" style="margin-bottom:0">MATCH HISTORY</h2>
      <div class="log-filter-row" id="logFilterRow" style="display:none">
        <span class="filter-label">FILTERED: <span id="filterLabel"></span></span>
        <button class="clear-btn" onclick="clearFilter()">&#10005; SHOW ALL</button>
      </div>
    </div>
    <div class="table-wrap" style="margin-top:1.4rem">
      ${tableHtml}
    </div>`;
}

// ── Carousel navigation ───────────────────────────────────────────────────────

function scrollCarousel(dir) {
  const c    = document.getElementById('gameCarousel');
  const card = c.querySelector('.game-card');
  if (!card) return;
  const gap = parseFloat(getComputedStyle(c).gap) || 12;
  c.scrollBy({ left: dir * (card.offsetWidth + gap) * 4, behavior: 'smooth' });
}

// ── Game selection & Games Log filter ─────────────────────────────────────────

let selectedCard = null;

function selectGame(card) {
  if (selectedCard && selectedCard !== card) selectedCard.classList.remove('selected');

  if (selectedCard === card) {
    card.classList.remove('selected');
    selectedCard = null;
    clearFilter();
    return;
  }

  card.classList.add('selected');
  selectedCard = card;
  filterLog(card.dataset.opponent);
  document.getElementById('games-log').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function filterLog(opponent) {
  const tbody = document.getElementById('gamesLogBody');
  if (!tbody) return;

  const rows = Array.from(tbody.querySelectorAll('tr'));
  let visible = 0;
  rows.forEach(row => {
    const match = (row.dataset.teams || '').split('|').includes(opponent);
    row.style.display = match ? '' : 'none';
    if (match) visible++;
  });

  document.getElementById('logFilterRow').style.display = 'flex';
  document.getElementById('filterLabel').textContent = opponent;

  let noMatch = document.getElementById('logNoMatch');
  if (visible === 0) {
    if (!noMatch) {
      noMatch = document.createElement('tr');
      noMatch.id = 'logNoMatch';
      noMatch.innerHTML = '<td colspan="6" class="log-no-match">-- NO SCORED GAMES VS THIS OPPONENT YET --</td>';
      tbody.appendChild(noMatch);
    }
    noMatch.style.display = '';
  } else if (noMatch) {
    noMatch.style.display = 'none';
  }
}

function clearFilter() {
  const tbody = document.getElementById('gamesLogBody');
  if (!tbody) return;
  Array.from(tbody.querySelectorAll('tr')).forEach(row => row.style.display = '');
  const noMatch = document.getElementById('logNoMatch');
  if (noMatch) noMatch.style.display = 'none';
  document.getElementById('logFilterRow').style.display = 'none';
  if (selectedCard) { selectedCard.classList.remove('selected'); selectedCard = null; }
}
