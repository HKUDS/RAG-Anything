(() => {
  const results = {};

  // Check for JSON-LD
  const jsonld = document.querySelectorAll('script[type="application/ld+json"]');
  results.jsonld = Array.from(jsonld).map(s => {
    try { return JSON.parse(s.textContent); } catch(e) { return s.textContent.substring(0, 500); }
  });

  // Check for any dollar amounts in the page
  const fullText = document.body.textContent;
  const dollarRegex = /\$[\d,]+(\.\d{2})?/g;
  const dollarMatches = fullText.match(dollarRegex) || [];
  results.dollarAmounts = dollarMatches;

  // Check for common pricing patterns
  const priceKwRegex = /(starting at|from|priced at|per user|per seat|per month|monthly|annually|\/month|\/year|\/mo|free|starter|professional|enterprise|business|team)/gi;
  const pricePatterns = fullText.match(priceKwRegex) || [];
  results.priceKeywords = [...new Set(pricePatterns)];

  // Look for any pricing-related containers
  const allDivs = document.querySelectorAll('div, section, article');
  let pricingRelated = [];
  allDivs.forEach(el => {
    const cls = (el.className || '').toString().toLowerCase();
    const id = (el.id || '').toString().toLowerCase();
    if (cls.includes('price') || cls.includes('plan') || cls.includes('tier') || cls.includes('package') ||
        id.includes('price') || id.includes('plan') || id.includes('tier') || id.includes('package')) {
      const text = el.textContent.trim().substring(0, 300).replace(/\s+/g, ' ');
      if (text.length > 20) pricingRelated.push(text);
    }
  });
  results.pricingContainers = pricingRelated.slice(0, 10);

  // Check page structure - all headings
  results.headings = Array.from(document.querySelectorAll('h1,h2,h3,h4')).map(h => h.textContent.trim()).filter(Boolean);

  // Check all links in the page for pricing pages
  results.links = Array.from(document.querySelectorAll('a[href*="pric"], a[href*="plan"], a[href*="purchase"], a[href*="signup"]')).map(a => ({
    text: a.textContent.trim(),
    href: a.href
  }));

  return JSON.stringify(results, null, 2);
})()
