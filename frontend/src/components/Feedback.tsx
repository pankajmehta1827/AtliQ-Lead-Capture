import { useState } from "react";
import { api } from "../api";

/** HAX G15: a quick "helpful / not helpful" on AI output, with an optional reason. Logged to the action log. */
export default function Feedback({
  feature,
  dealId,
  refText,
}: {
  feature: "email_draft" | "pipeline_answer";
  dealId?: number;
  refText?: string;
}) {
  const [rating, setRating] = useState<"up" | "down" | null>(null);
  const [comment, setComment] = useState("");
  const [sent, setSent] = useState(false);

  async function send(r: "up" | "down", text = "") {
    try {
      await api("/api/feedback", {
        method: "POST",
        json: { feature, rating: r, deal_id: dealId ?? null, comment: text, ref: (refText ?? "").slice(0, 300) },
      });
      setSent(true);
    } catch {
      /* feedback is best-effort; never block the user */
    }
  }

  if (sent) return <div className="feedback small muted">Thanks, your feedback was noted.</div>;

  return (
    <div className="feedback small">
      {rating !== "down" ? (
        <>
          <span className="muted">Was this useful?</span>
          <button
            type="button"
            className={rating === "up" ? "on" : ""}
            aria-pressed={rating === "up"}
            onClick={() => {
              setRating("up");
              send("up");
            }}
          >
            Yes
          </button>
          <button type="button" aria-pressed={false} onClick={() => setRating("down")}>
            No
          </button>
        </>
      ) : (
        <form
          className="feedback-form"
          onSubmit={(e) => {
            e.preventDefault();
            send("down", comment.trim());
          }}
        >
          <input
            autoFocus
            aria-label="What was wrong?"
            placeholder="What was wrong? (optional)"
            value={comment}
            maxLength={500}
            onChange={(e) => setComment(e.target.value)}
          />
          <button className="primary">Send</button>
          <button type="button" onClick={() => setRating(null)}>
            Cancel
          </button>
        </form>
      )}
    </div>
  );
}
