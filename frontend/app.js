const API = window.location.origin;

// ── Helpers ──────────────────────────────────────────────────────────────────

function $(id) { return document.getElementById(id); }

function autoResize(el) {
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 120) + 'px';
}

function toggleSidebar() {
    document.getElementById("sidebar").classList.toggle("open");
}

function toggleTheme() {
    const html = document.documentElement;
    const isDark = html.getAttribute("data-theme") === "dark";
    const newTheme = isDark ? "light" : "dark";
    html.setAttribute("data-theme", newTheme);
    $("theme-icon").textContent = isDark ? "🌙" : "☀️";
    localStorage.setItem("studify-theme", newTheme);
}

function initTheme() {
    const saved = localStorage.getItem("studify-theme");
    if (saved) {
        // User previously toggled — respect their choice
        document.documentElement.setAttribute("data-theme", saved);
        $("theme-icon").textContent = saved === "dark" ? "☀️" : "🌙";
    } else {
        // No saved preference — follow system setting
        const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
        document.documentElement.setAttribute("data-theme", prefersDark ? "dark" : "light");
        $("theme-icon").textContent = prefersDark ? "☀️" : "🌙";
    }
}

function useExample(btn) {
    $("query-input").value = btn.textContent.trim();
    autoResize($("query-input"));
    solveQuery();
}

// Convert markdown to basic HTML
function renderMarkdown(text) {
    // Handle markdown tables first (before other replacements)
    text = text.replace(
        /((\|.+\|\n?)+)/gm,
        (match) => {
            const rows = match.trim().split("\n").filter(r => r.trim());
            if (rows.length < 2) return match;

            let html = '<table class="md-table"><thead><tr>';
            const headers = rows[0].split("|").filter(c => c.trim() !== "");
            headers.forEach(h => {
                html += `<th>${h.trim()}</th>`;
            });
            html += "</tr></thead><tbody>";

            // Skip the separator row (row[1] is always ---|---  etc.)
            rows.slice(2).forEach(row => {
                const cells = row.split("|").filter(c => c.trim() !== "");
                html += "<tr>";
                cells.forEach(c => { html += `<td>${c.trim()}</td>`; });
                html += "</tr>";
            });

            html += "</tbody></table>";
            return html;
        }
    );

    return text
        .replace(/^### (.+)$/gm, "<h3>$1</h3>")
        .replace(/^## (.+)$/gm, "<h2>$1</h2>")
        .replace(/^# (.+)$/gm, "<h1>$1</h1>")
        .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
        .replace(/\*(.+?)\*/g, "<em>$1</em>")
        .replace(/^---$/gm, "<hr>")
        .replace(/^> (.+)$/gm, "<blockquote>$1</blockquote>")
        .replace(/\n\n/g, "</p><p>")
        .trim();
}

// ── Solve ─────────────────────────────────────────────────────────────────────

async function solveQuery() {
    const query = $("query-input").value.trim();
    if (!query) return;

    // Show loading
    $("loading-overlay").classList.remove("hidden");
    $("send-btn").disabled = true;

    try {
        const res  = await fetch(`${API}/solve`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ query })
        });
        const data = await res.json();

        if (data.success) {
            displayResult(query, data);
            loadStats();
            loadHistory();
        } else {
            alert("Error: " + (data.error || "Unknown error"));
        }

    } catch (err) {
        alert("Cannot reach backend. Is uvicorn running on port 8000?");
    } finally {
        $("loading-overlay").classList.add("hidden");
        $("send-btn").disabled = false;
        $("query-input").value = "";
        $("query-input").style.height = "auto";
    }
}

// ── Display result ────────────────────────────────────────────────────────────

function displayResult(query, data) {
    // Hide welcome screen
    $("welcome").classList.add("hidden");

    // Query bubble
    $("query-bubble").textContent = query;

    // Operation badge and expression
    $("op-badge").textContent = (data.operation || "").replace(/_/g, " ");
    $("expr-tag").textContent  = data.expression || "";

    // Symbolic result — use MathJax direct conversion (most reliable method)
    const symEl = $("sym-result-math");
    symEl.innerHTML = "";

    if (data.symbolic_result_latex && window.MathJax && MathJax.tex2chtml) {
        try {
            const mathNode = MathJax.tex2chtml(
                `\\displaystyle ${data.symbolic_result_latex}`,
                { display: false }
            );
            symEl.appendChild(mathNode);
            // Push updated CSS to document
            MathJax.startup.document.clear();
            MathJax.startup.document.updateDocument();
        } catch (e) {
            symEl.textContent = data.symbolic_result || "";
        }
    } else {
        symEl.textContent = data.symbolic_result || "";
    }

    // Explanation — render markdown then let MathJax auto-scan
    const expEl = $("explanation");
    expEl.innerHTML = renderMarkdown(data.explanation || "");

    // Show result card
    $("result-card").classList.remove("hidden");

    // Typeset explanation area (MathJax scans for $$ and \( delimiters)
    if (window.MathJax && MathJax.startup) {
        MathJax.startup.promise.then(() => {
            MathJax.typesetPromise([expEl])
                .catch(err => console.warn("MathJax explanation error:", err));
        });
    }

    // Scroll to top of result
    $("results-area").scrollTo({ top: 0, behavior: "smooth" });
}

// ── Stats ─────────────────────────────────────────────────────────────────────

async function loadStats() {
    try {
        const res  = await fetch(`${API}/stats`);
        const data = await res.json();
        $("stat-total").textContent   = data.total_queries;
        $("stat-success").textContent = data.success_rate;
    } catch (_) {}
}

// ── History ───────────────────────────────────────────────────────────────────

async function loadHistory() {
    try {
        const res  = await fetch(`${API}/history?limit=15`);
        const data = await res.json();
        const list = $("history-list");

        if (!data.history.length) {
            list.innerHTML = '<div class="history-empty">No queries yet</div>';
            return;
        }

        list.innerHTML = "";
        data.history.forEach(item => {
            const div = document.createElement("div");
            div.className = "history-item";
            div.innerHTML = `
                <div class="h-query">${item.query}</div>
                <div class="h-meta">
                    <span class="h-dot ${item.success ? 'ok' : 'err'}">●</span>
                    ${item.operation || "unknown"} ·
                    ${item.timestamp.slice(0,16).replace("T"," ")}
                </div>`;

            div.onclick = () => {
                if (item.success && item.symbolic_result) {
                    displayResult(item.query, {
                        operation:            item.operation,
                        expression:           item.expression,
                        symbolic_result:      item.symbolic_result,
                        symbolic_result_latex: item.symbolic_result_latex || null,
                        explanation:          item.explanation || ""
                    });
                } else {
                    $("query-input").value = item.query;
                }
            };

            list.appendChild(div);
        });

    } catch (_) {}
}

// ── Keyboard: Enter to send ───────────────────────────────────────────────────

$("query-input").addEventListener("keydown", e => {
    if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        solveQuery();
    }
});

// ── Init ──────────────────────────────────────────────────────────────────────
initTheme();
loadStats();
loadHistory();

// Listen for system theme changes (e.g. user switches Mac to dark mode)
window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", e => {
    // Only follow system if user hasn't manually toggled
    if (!localStorage.getItem("studify-theme")) {
        document.documentElement.setAttribute("data-theme", e.matches ? "dark" : "light");
        $("theme-icon").textContent = e.matches ? "☀️" : "🌙";
    }
});