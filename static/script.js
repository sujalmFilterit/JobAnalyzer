const jobForm = document.querySelector('.form');
const descriptionInput = document.getElementById('description');
const companyInput = document.getElementById('company');
const resultBox = document.querySelector('.result-box');
const loaderWrap = document.querySelector('.loader-wrap');

jobForm.addEventListener('submit', async (e) => {
    e.preventDefault();

    const textToAnalyze = descriptionInput.value.trim();
    const companyToAnalyze = companyInput ? companyInput.value.trim() : "";

    if (!textToAnalyze) {
        alert("Please enter a job description");
        return;
    }

    try {
        // 1. Clear old results and SHOW the spinner
        resultBox.innerHTML = '';
        if (loaderWrap) loaderWrap.style.display = 'flex';
        // Scroll result panel into view on mobile
        resultBox.scrollIntoView({ behavior: 'smooth', block: 'nearest' });

        // 2. Fetch data from Python Backend
        const response = await fetch('http://127.0.0.1:8000/predict', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                "description": textToAnalyze,
                "company": companyToAnalyze
            })
        });

        const result = await response.json();
        
        // 3. HIDE the spinner once data arrives
        if (loaderWrap) loaderWrap.style.display = 'none';
        
        // 4. Setup styling based on AI result
        const isFraud = result.result.toLowerCase().includes("suspicious") || result.result.toLowerCase().includes("fraudulent");
        const accentColor = isFraud ? "#ef4444" : "#22c55e";
        const accentBg    = isFraud ? "rgba(239,68,68,0.08)"  : "rgba(34,197,94,0.08)";
        const accentBdr   = isFraud ? "rgba(239,68,68,0.2)"   : "rgba(34,197,94,0.2)";
        const verdictIcon = isFraud
            ? `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>`
            : `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><polyline points="9 12 11 14 15 10"/></svg>`;

        // 5. Build Company Verification Card
        let companyVerificationHTML = "";
        if (companyToAnalyze !== "") {
            if (result.company_exists) {
                const info = result.company_info;
                companyVerificationHTML = `
                <div class="res-company-card res-company-card--verified">
                    <div class="res-company-header">
                        <div class="res-company-badge res-company-badge--green">
                            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>
                            Verified Company
                        </div>
                        <span class="res-company-rating">⭐ ${info.rating} <span class="res-company-reviews">(${info.reviews} reviews)</span></span>
                    </div>
                    <p class="res-company-name">${result.matched_company}</p>
                    <div class="res-company-grid">
                        <div class="res-company-item"><span class="res-company-item-label">Type</span><span class="res-company-item-val">${info.company_type}</span></div>
                        <div class="res-company-item"><span class="res-company-item-label">Industry</span><span class="res-company-item-val">${info.industry}</span></div>
                        <div class="res-company-item"><span class="res-company-item-label">Founded</span><span class="res-company-item-val">${info.age}</span></div>
                        <div class="res-company-item"><span class="res-company-item-label">Employees</span><span class="res-company-item-val">${info.employees}</span></div>
                    </div>
                    <div class="res-company-location">
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/></svg>
                        ${info.location}
                    </div>
                </div>`;
            } else {
                companyVerificationHTML = `
                <div class="res-company-card res-company-card--unverified">
                    <div class="res-company-badge res-company-badge--red">
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
                        Company Not Found
                    </div>
                    <p class="res-company-warn">The company "<strong>${companyToAnalyze}</strong>" could not be verified in our corporate database. This is a significant red flag.</p>
                </div>`;
            }
        }

        // 6. Render premium result card
        resultBox.innerHTML = `
            <div class="res-wrap">
                <div class="res-verdict" style="background:${accentBg}; border-color:${accentBdr};">
                    <div class="res-verdict-icon" style="color:${accentColor};">${verdictIcon}</div>
                    <div class="res-verdict-body">
                        <p class="res-verdict-text" style="color:${accentColor};">${result.result}</p>
                        <p class="res-verdict-conf">AI Confidence: <strong style="color:${accentColor};">${result.confidence}</strong></p>
                    </div>
                </div>
                ${companyVerificationHTML}
            </div>
        `;

    } catch (error) {
        console.error("Connection failed:", error);
        if (loaderWrap) loaderWrap.style.display = 'none';
        resultBox.innerHTML = '<p style="color: #ef4444; text-align: center; padding: 20px;">❌ Error: Could not connect to API.</p>';
    }
});