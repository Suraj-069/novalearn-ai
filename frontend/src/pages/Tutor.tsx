import { ArrowUp, BookCheck, Bot, Mic, MessageSquarePlus, ShieldAlert, Sparkles, Speaker, Square, Trash2 } from "lucide-react";
import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { Link, useParams } from "react-router-dom";

import { CapabilityNote } from "@/components/CapabilityNote";
import { SourceViewer, locationLabel } from "@/components/source/SourceViewer";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/Feedback";
import { useAsync } from "@/hooks/useAsync";
import { useAuth } from "@/hooks/useAuth";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { useToast } from "@/hooks/useToast";
import { timeAgo } from "@/lib/format";
import { ApiError, api } from "@/services/api";
import type { AnswerMode, ChatMessage, Citation, ExplainMode } from "@/types";

const MODES: { id: ExplainMode | ""; label: string }[] = [
  { id: "", label: "My default style" }, { id: "simple", label: "Simple" }, { id: "detailed", label: "Detailed" },
  { id: "example", label: "With an example" }, { id: "compare", label: "Compare" }, { id: "summary", label: "Revision summary" },
];

const MODE_LABEL: Record<AnswerMode, { text: string; tone: "ok" | "cyan" | "warn" }> = {
  llm: { text: "From your course material", tone: "ok" },
  extractive: { text: "Passages from your material", tone: "cyan" },
  unsupported: { text: "Not found in your material", tone: "warn" },
  general: { text: "General explanation, not from your course", tone: "warn" },
};

type BrowserRecognition = {
  lang: string; continuous: boolean; interimResults: boolean;
  onresult: ((event: Event) => void) | null; onerror: (() => void) | null; onend: (() => void) | null;
  start: () => void; stop: () => void;
};
type SpeechWindow = Window & { SpeechRecognition?: new () => BrowserRecognition; webkitSpeechRecognition?: new () => BrowserRecognition };

/** Turn "[2]" markers into buttons, but only for citations that actually exist. */
function Answer({ m, onOpen }: { m: ChatMessage; onOpen: (c: Citation) => void }) {
  const byN = new Map(m.citations.map((c) => [c.n, c]));
  return (
    <p className="whitespace-pre-wrap leading-relaxed">
      {m.content.split(/(\[\d+\])/g).map((part, i) => {
        const hit = /^\[(\d+)\]$/.exec(part);
        const c = hit ? byN.get(Number(hit[1])) : undefined;
        return c
          ? <button key={i} type="button" onClick={() => onOpen(c)} aria-label={`Open source ${c.n}: ${c.filename}, ${locationLabel(c)}`}
              className="mx-0.5 rounded-md bg-nova-100 px-1.5 py-0.5 align-baseline text-xs font-semibold text-nova-700 hover:bg-nova-600 hover:text-white">{c.n}</button>
          : <span key={i}>{part}</span>;
      })}
    </p>
  );
}

function AssistantBubble({ m, onOpen }: { m: ChatMessage; onOpen: (c: Citation) => void }) {
  const label = m.mode ? MODE_LABEL[m.mode] : null;
  return (
    <div className="flex gap-3">
      <div className="mt-1 grid h-8 w-8 shrink-0 place-items-center rounded-xl bg-gradient-to-br from-nova-600 to-violet text-white"><Bot className="h-4 w-4" aria-hidden /></div>
      <div className="min-w-0 max-w-[46rem] flex-1 rounded-card border border-line bg-white p-4 shadow-card">
        {label && <div className="mb-2"><Badge tone={label.tone} icon={m.mode === "unsupported" ? <ShieldAlert className="h-3 w-3" /> : m.mode === "general" ? <Sparkles className="h-3 w-3" /> : <BookCheck className="h-3 w-3" />}>{label.text}</Badge></div>}
        <Answer m={m} onOpen={onOpen} />
        {m.citations.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-2 border-t border-line pt-3">
            {m.citations.map((c) => (
              <button key={c.n} type="button" onClick={() => onOpen(c)} disabled={!c.available}
                className="max-w-full truncate rounded-full border border-line bg-slate-50 px-3 py-1 text-xs text-ink-soft hover:border-nova-500 hover:text-nova-700 disabled:opacity-60">
                <span className="font-semibold text-nova-700">{c.n}</span> {c.filename} · {c.available ? locationLabel(c) : "removed"}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

export default function Tutor() {
  const { id = "" } = useParams();
  const toast = useToast();
  const { user } = useAuth();
  const desktop = useMediaQuery("(min-width: 1024px)");
  const course = useAsync(() => api.course(id), [id]);
  const topics = useAsync(() => api.topics(id), [id]);
  const convs = useAsync(() => api.conversations(id), [id]);
  const suggestions = useAsync(() => api.suggestions(id), [id]);
  const caps = useAsync(() => api.capabilities(), []);

  const [convId, setConvId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [text, setText] = useState("");
  const [topicId, setTopicId] = useState("");
  const [mode, setMode] = useState<ExplainMode | "">("");
  const [general, setGeneral] = useState(false);
  const [sending, setSending] = useState(false);
  const [open, setOpen] = useState<Citation | null>(null);
  const [fullText, setFullText] = useState<string | undefined>();
  const [listening, setListening] = useState(false);
  const recognition = useRef<BrowserRecognition | null>(null);
  const end = useRef<HTMLDivElement>(null);

  const speechWindow = window as SpeechWindow;
  const SpeechRecognition = speechWindow.SpeechRecognition ?? speechWindow.webkitSpeechRecognition;
  const voiceOutputAvailable = "speechSynthesis" in window;
  const speechLocale = ({ English: "en-US", Hindi: "hi-IN", Marathi: "mr-IN", Spanish: "es-ES", French: "fr-FR", German: "de-DE" } as Record<string, string>)[user?.language ?? ""] ?? navigator.language ?? "en-US";

  useEffect(() => () => { recognition.current?.stop(); window.speechSynthesis?.cancel(); }, []);

  function toggleVoiceInput() {
    if (listening) { recognition.current?.stop(); setListening(false); return; }
    if (!SpeechRecognition) return;
    const instance = new SpeechRecognition();
    instance.lang = speechLocale;
    instance.continuous = false;
    instance.interimResults = false;
    instance.onresult = (raw: Event) => {
      const event = raw as Event & { results: ArrayLike<ArrayLike<{ transcript: string }>>; resultIndex: number };
      const transcript = event.results[event.resultIndex]?.[0]?.transcript;
      if (transcript) setText((current) => `${current}${current ? " " : ""}${transcript}`.slice(0, 2000));
    };
    instance.onerror = () => { setListening(false); toast.error("Browser speech recognition stopped. You can type your question instead."); };
    instance.onend = () => setListening(false);
    recognition.current = instance;
    try { instance.start(); setListening(true); }
    catch { setListening(false); toast.error("Could not start speech recognition. You can type your question instead."); }
  }

  function speakAnswer(message: ChatMessage) {
    if (!voiceOutputAvailable) return;
    window.speechSynthesis.cancel();
    const speech = new SpeechSynthesisUtterance(message.content.replace(/\[\d+\]/g, ""));
    speech.lang = speechLocale;
    window.speechSynthesis.speak(speech);
  }

  useEffect(() => { end.current?.scrollIntoView({ behavior: "smooth", block: "end" }); }, [messages, sending]);

  async function openCitation(c: Citation) {
    setOpen(c); setFullText(undefined);
    if (c.available) api.openChunkText(c.chunk_id).then(setFullText).catch(() => undefined);
  }

  async function loadConversation(cid: string) {
    try { setMessages(await api.messages(cid)); setConvId(cid); setOpen(null); }
    catch (e) { toast.error(e instanceof ApiError ? e.message : "Couldn't load that conversation."); }
  }

  function newChat() { setConvId(null); setMessages([]); setOpen(null); }

  async function send(question: string) {
    const q = question.trim();
    if (!q || sending) return;
    setText(""); setSending(true);
    const temp: ChatMessage = { id: `tmp-${Date.now()}`, role: "user", content: q, citations: [], grounded: null, mode: null, created_at: new Date().toISOString() };
    setMessages((l) => [...l, temp]);
    try {
      const r = await api.chat(id, { question: q, conversation_id: convId, topic_id: topicId || null, mode: mode || null, allow_general: general });
      setConvId(r.conversation_id);
      setMessages((l) => [...l.filter((m) => m.id !== temp.id), r.user_message, r.assistant_message]);
      void convs.reload();
    } catch (e) {
      setMessages((l) => l.filter((m) => m.id !== temp.id));
      setText(q);
      toast.error(e instanceof ApiError ? e.message : "The tutor couldn't answer right now.");
    } finally { setSending(false); }
  }

  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void send(text); } };

  if (course.error) return <ErrorState message={course.error.message} onRetry={course.reload} />;
  const hasContent = (course.data?.topic_count ?? 0) > 0;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <Link to={`/courses/${id}`} className="text-sm text-ink-muted hover:text-ink">← {course.data?.title ?? "Course"}</Link>
          <h1 className="text-2xl font-semibold sm:text-3xl">AI tutor</h1>
        </div>
        <Button variant="secondary" icon={<MessageSquarePlus className="h-4 w-4" />} onClick={newChat}>New chat</Button>
      </div>
      <CapabilityNote />

      {course.data && !hasContent ? (
        <div className="card"><EmptyState icon={<Bot className="h-5 w-5" />} title="Nothing to ask about yet"
          action={<Link to={`/courses/${id}`}><Button>Go to course material</Button></Link>}>
          The tutor answers only from indexed course material. Upload a file and wait for it to finish processing.</EmptyState></div>
      ) : (
        <div className="grid grid-cols-[minmax(0,1fr)] gap-4 lg:grid-cols-[220px_minmax(0,1fr)_380px]">
          {/* History */}
          <aside className="hidden lg:block" aria-label="Conversation history">
            <h2 className="mb-2 text-sm font-semibold text-ink-soft">History</h2>
            {convs.data && convs.data.length === 0 && <p className="text-sm text-ink-muted">No conversations yet.</p>}
            <ul className="space-y-1">
              {convs.data?.map((c) => (
                <li key={c.id} className="group flex items-center gap-1">
                  <button onClick={() => loadConversation(c.id)} className={`min-w-0 flex-1 rounded-ctl px-3 py-2 text-left text-sm ${convId === c.id ? "bg-nova-50 text-nova-700" : "hover:bg-slate-100"}`}>
                    <div className="truncate font-medium">{c.title}</div><div className="text-xs text-ink-muted">{timeAgo(c.created_at)}</div>
                  </button>
                  <button aria-label={`Delete conversation ${c.title}`} className="rounded p-1.5 text-ink-muted opacity-0 hover:text-bad focus:opacity-100 group-hover:opacity-100"
                    onClick={() => api.deleteConversation(c.id).then(() => { if (convId === c.id) newChat(); void convs.reload(); }).catch(() => toast.error("Couldn't delete."))}><Trash2 className="h-4 w-4" /></button>
                </li>
              ))}
            </ul>
          </aside>

          {/* Chat */}
          <section className="flex min-h-[32rem] min-w-0 flex-col rounded-card border border-line bg-canvas/60" aria-label="Conversation">
            <div className="flex flex-wrap gap-3 border-b border-line bg-white/70 p-3">
              <label className="flex min-w-0 max-w-full items-center gap-2 text-sm"><span className="shrink-0 text-ink-muted">Topic</span>
                <select value={topicId} onChange={(e) => setTopicId(e.target.value)} className="input !w-auto min-w-0 max-w-[11rem] !py-1.5 sm:max-w-xs">
                  <option value="">Whole course</option>
                  {topics.data?.map((t) => <option key={t.id} value={t.id}>{t.parent_id ? "— " : ""}{t.name}</option>)}
                </select></label>
              <label className="flex min-w-0 max-w-full items-center gap-2 text-sm"><span className="shrink-0 text-ink-muted">Style</span>
                <select value={mode} onChange={(e) => setMode(e.target.value as ExplainMode | "")} className="input !w-auto min-w-0 max-w-[11rem] !py-1.5 sm:max-w-xs">
                  {MODES.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}</select></label>
              {convs.data && convs.data.length > 0 && !desktop && (
                <label className="flex min-w-0 max-w-full items-center gap-2 text-sm"><span className="shrink-0 text-ink-muted">History</span>
                  <select value={convId ?? ""} onChange={(e) => e.target.value ? void loadConversation(e.target.value) : newChat()} className="input !w-auto min-w-0 max-w-[11rem] !py-1.5 sm:max-w-xs">
                    <option value="">New chat</option>{convs.data.map((c) => <option key={c.id} value={c.id}>{c.title}</option>)}</select></label>
              )}
            </div>

            <div className="flex-1 space-y-5 overflow-y-auto p-4" aria-live="polite">
              {messages.length === 0 && (
                <div className="py-6 text-center">
                  <p className="font-medium">Ask anything about {course.data?.title ?? "your course"}</p>
                  <p className="mt-1 text-sm text-ink-muted">Every answer links to the page, slide or moment it came from.</p>
                  <div className="mt-5 flex flex-wrap justify-center gap-2">
                    {suggestions.loading && <Skeleton className="h-9 w-48" />}
                    {suggestions.data?.map((s) => <button key={s} onClick={() => void send(s)} className="rounded-full border border-line bg-white px-4 py-2 text-sm hover:border-nova-500 hover:text-nova-700">{s}</button>)}
                  </div>
                </div>
              )}
              {messages.map((m) => m.role === "user"
                ? <div key={m.id} className="flex justify-end"><p className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-md bg-nova-600 px-4 py-2.5 text-white">{m.content}</p></div>
                : <div key={m.id} className="space-y-2"><AssistantBubble m={m} onOpen={openCitation} />
                  {voiceOutputAvailable && <div className="pl-11"><button type="button" onClick={() => speakAnswer(m)} className="inline-flex items-center gap-1 text-xs text-ink-muted hover:text-nova-700"><Speaker className="h-3.5 w-3.5" aria-hidden />Read answer aloud</button></div>}</div>)}
              {sending && <div className="flex gap-3"><div className="skeleton h-8 w-8 shrink-0 !rounded-xl" /><div className="skeleton h-16 w-2/3" /><span className="sr-only">Searching your material…</span></div>}
              <div ref={end} />
            </div>

            <div className="border-t border-line bg-white p-3">
              {caps.data?.llm.configured && (
                <label className="mb-2 flex items-center gap-2 text-[13px] text-ink-muted">
                  <input type="checkbox" checked={general} onChange={(e) => setGeneral(e.target.checked)} />
                  If my material doesn't cover it, give a general explanation (clearly labelled, no citations)
                </label>
              )}
              <div className="flex items-end gap-2">
                <label htmlFor="q" className="sr-only">Your question</label>
                <textarea id="q" value={text} onChange={(e) => setText(e.target.value)} onKeyDown={onKey} rows={2} maxLength={2000}
                  placeholder="Ask a question about your material…" className="input flex-1 resize-none" />
                {SpeechRecognition && <Button variant="secondary" onClick={toggleVoiceInput} aria-label={listening ? "Stop voice input" : "Ask by voice"} icon={listening ? <Square className="h-4 w-4" /> : <Mic className="h-4 w-4" />}>{listening ? "Stop" : "Voice"}</Button>}
                <Button onClick={() => void send(text)} loading={sending} disabled={!text.trim()} aria-label="Send question" icon={<ArrowUp className="h-4 w-4" />}>Send</Button>
              </div>
              <p className="mt-1 text-xs text-ink-muted">Voice input and read-aloud use browser speech features when available; type questions or read the text answer otherwise.</p>
            </div>
          </section>

          {/* Source panel */}
          {desktop && (
            <aside className="card h-fit max-h-[calc(100vh-8rem)] min-w-0 overflow-y-auto p-5 lg:sticky lg:top-6" aria-label="Source">
              <h2 className="mb-3 text-sm font-semibold text-ink-soft">Source</h2>
              {open ? <SourceViewer citation={open} full={fullText} /> : <p className="text-sm text-ink-muted">Select a numbered citation in an answer to open the exact page, slide or video moment here.</p>}
            </aside>
          )}
        </div>
      )}

      {!desktop && (
        <Dialog open={open !== null} onClose={() => setOpen(null)} title="Source">
          {open && <div className="max-h-[70vh] overflow-y-auto"><SourceViewer citation={open} full={fullText} /></div>}
        </Dialog>
      )}
    </div>
  );
}
