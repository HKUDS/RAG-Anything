import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { CheckCircle2, ChevronRight, Database, FilePlus2, KeyRound, MessageSquare } from 'lucide-react'
import { getDocuments } from '../api/client'
import { useReadiness } from '../context/readiness'

export default function Dashboard() {
  const { fullyConfigured, indexedCount, isLoading } = useReadiness()
  const { data: documents = [] } = useQuery({ queryKey: ['documents'], queryFn: getDocuments })

  const totalDocs = documents.length
  const runningJobs = documents.filter((d) => d.status === 'processing').length
  const failedDocs = documents.filter((d) => d.status === 'failed').length

  const step1Done = fullyConfigured
  const step2Done = indexedCount > 0
  const activeStep = !step1Done ? 1 : !step2Done ? 2 : 3

  return (
    <section className="page">
      <div className="page-header">
        <div>
          <h1>RAG-Anything Studio</h1>
          <p>Local multimodal RAG workspace</p>
        </div>
        <div className="actions">
          <Link className="button primary" to="/documents/new">
            <FilePlus2 size={18} />
            Upload Document
          </Link>
          <Link className="button" to="/query">
            <MessageSquare size={18} />
            Query
          </Link>
        </div>
      </div>

      {!isLoading && (
        <div className="onboarding-track">
          <OnboardingStep
            icon={<KeyRound size={20} />}
            title="Configure API keys"
            description="Set your LLM and Embedding provider credentials in Settings."
            done={step1Done}
            active={activeStep === 1}
            action={<Link className="button primary step-action" to="/settings">Open Settings <ChevronRight size={15} /></Link>}
          />
          <div className="onboarding-connector" aria-hidden="true" />
          <OnboardingStep
            icon={<FilePlus2 size={20} />}
            title="Upload & index a document"
            description="Upload a PDF, image, or Office file and let RAG-Anything parse and index it."
            done={step2Done}
            active={activeStep === 2}
            action={<Link className="button primary step-action" to="/documents/new">Upload <ChevronRight size={15} /></Link>}
          />
          <div className="onboarding-connector" aria-hidden="true" />
          <OnboardingStep
            icon={<MessageSquare size={20} />}
            title="Query your knowledge base"
            description="Ask questions across all indexed documents using hybrid RAG retrieval."
            done={false}
            active={activeStep === 3}
            action={<Link className="button primary step-action" to="/query">Go to Query <ChevronRight size={15} /></Link>}
          />
        </div>
      )}

      <div className="metric-grid">
        <MetricCard label="Total documents" value={totalDocs} />
        <MetricCard label="Indexed" value={indexedCount} highlight />
        <MetricCard label="Processing" value={runningJobs} />
        <MetricCard label="Failed" value={failedDocs} warn={failedDocs > 0} />
      </div>

      {totalDocs > 0 && (
        <div className="panel stack">
          <div className="panel-header-row">
            <h2><Database size={16} style={{ display: 'inline', verticalAlign: 'middle', marginRight: 6 }} />Recent documents</h2>
            <Link className="link-subtle" to="/documents">View all</Link>
          </div>
          <div className="doc-list">
            {documents.slice(0, 5).map((doc) => (
              <div key={doc.id} className="doc-list-row">
                <span className="doc-name">{doc.filename}</span>
                <span className={`status status-${doc.status}`}>{doc.status}</span>
                <span className="doc-date">{new Date(doc.created_at).toLocaleDateString()}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </section>
  )
}

interface OnboardingStepProps {
  icon: React.ReactNode
  title: string
  description: string
  done: boolean
  active: boolean
  action: React.ReactNode
}

function OnboardingStep({ icon, title, description, done, active, action }: OnboardingStepProps) {
  return (
    <div className={`onboarding-step ${done ? 'onboarding-step--done' : active ? 'onboarding-step--active' : 'onboarding-step--pending'}`}>
      <div className="onboarding-step__num">
        {done ? <CheckCircle2 size={18} /> : icon}
      </div>
      <div className="onboarding-step__body">
        <strong>{title}</strong>
        <p>{description}</p>
      </div>
      {done
        ? <span className="onboarding-done-label">Done</span>
        : active
          ? <div className="onboarding-step__action">{action}</div>
          : null}
    </div>
  )
}

interface MetricCardProps {
  label: string
  value: number
  highlight?: boolean
  warn?: boolean
}

function MetricCard({ label, value, highlight, warn }: MetricCardProps) {
  return (
    <article className={`metric${highlight ? ' metric--highlight' : ''}${warn ? ' metric--warn' : ''}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </article>
  )
}
