import { RefreshCw, Search, Settings } from 'lucide-react'

export default function KnowledgeGraphPage() {
  return (
    <section className="graph-workspace">
      <div className="graph-toolbar">
        <button className="icon-button graph-refresh" type="button" title="Reload graph">
          <RefreshCw size={16} />
        </button>
        <select className="graph-select" defaultValue="">
          <option value="">Search node name...</option>
        </select>
        <div className="graph-search">
          <Search size={16} />
          <input placeholder="Search nodes in page..." />
        </div>
      </div>
      <div className="graph-empty">
        <span className="graph-empty-dot" />
        Empty(Try Reload Again)
      </div>
      <div className="graph-side-tools">
        <button className="icon-button" title="Layout"><span className="tool-grid-dot" /></button>
        <button className="icon-button" title="Reload"><RefreshCw size={15} /></button>
        <button className="icon-button" title="Settings"><Settings size={15} /></button>
      </div>
      <div className="graph-footer-note">D: 3&nbsp;&nbsp; Max: 1000</div>
    </section>
  )
}
