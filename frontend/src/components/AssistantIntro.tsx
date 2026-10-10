import { useState } from "react";
import { Icon } from "./ui";

const key = (user: string) => `atliq-intro-dismissed:${user}`;

export function introDismissed(user: string): boolean {
  try {
    return localStorage.getItem(key(user)) === "1";
  } catch {
    return false;
  }
}

export function resetIntro(user: string) {
  try {
    localStorage.removeItem(key(user));
  } catch {
    /* per-viewer convenience only */
  }
}

/** HAX G1 + G2: what the assistant can do, what it never does, and how well it works. Shown until dismissed. */
export default function AssistantIntro({ user }: { user: string }) {
  const [hidden, setHidden] = useState(() => introDismissed(user));
  if (hidden) return null;

  return (
    <section className="intro blueprint" aria-label="About the assistant">
      <div className="intro-head">
        <span className="kicker accent">
          <Icon name="sparkle" size={12} /> About your AI assistant
        </span>
        <button
          className="primary"
          onClick={() => {
            try {
              localStorage.setItem(key(user), "1");
            } catch {
              /* ignore */
            }
            setHidden(true);
          }}
        >
          Got it
        </button>
      </div>
      <div className="intro-grid">
        <div>
          <h3>What it does</h3>
          <ul>
            <li>Turns emails, meeting notes and LinkedIn chats you add into draft CRM records</li>
            <li>Finds next steps, revisit dates and unanswered proposals, and reminds you</li>
            <li>Drafts follow-up emails and answers questions about your pipeline</li>
          </ul>
        </div>
        <div>
          <h3>What it never does</h3>
          <ul>
            <li>Save anything to the CRM until you click Confirm</li>
            <li>Send emails or contact clients: you send every reply yourself</li>
            <li>Read contacts, threads or keywords you have excluded</li>
          </ul>
        </div>
        <div>
          <h3>How far to trust it</h3>
          <ul>
            <li>Drafts can be wrong or incomplete: every value quotes the sentence it came from, so check it</li>
            <li>Values it can't find are left empty, and unsure drafts are marked "Needs review"</li>
            <li>Tell us when an email draft or answer is off: use "Was this useful?"</li>
          </ul>
        </div>
      </div>
    </section>
  );
}
