import { useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
import MarkdownRenderer from "../components/ui/MarkdownRenderer";

export default function TermsAcceptancePage() {
  const navigate = useNavigate();
  const { user, termsSettings, acceptTerms, declineTerms } = useAuth();
  const { showError } = useToast();

  const isTermsEnabled = termsSettings.terms_enabled;
  const isAccepted = user?.terms_accepted ?? false;
  const hasContent = isTermsEnabled && !isAccepted && termsSettings.terms_content.trim().length > 0;

  if (!hasContent) {
    return null;
  }

  return (
    <section className="mx-auto max-w-2xl">
      <article className="rounded-2xl border border-black/10 bg-white/90 p-6 shadow-sm backdrop-blur">
        <h2 className="font-display text-2xl">Terms and Policies</h2>
        <p className="mt-2 text-sm text-black/65">
          Please review and accept the terms and policies to continue.
        </p>

        <div className="mt-4 max-h-[50vh] overflow-y-auto rounded-2xl border border-black/10 bg-[#fffdf7] p-5">
          {isTermsEnabled && termsSettings.terms_content ? (
            <MarkdownRenderer content={termsSettings.terms_content} />
          ) : (
            <p className="text-sm text-black/65">No terms and policies content has been configured.</p>
          )}
        </div>

        <div className="mt-6 flex items-center justify-end gap-3">
          <button
            type="button"
            onClick={() => {
              declineTerms();
            }}
            className="rounded-2xl border border-black/10 bg-white px-5 py-3 text-sm font-semibold text-black transition hover:border-black/20 hover:bg-black/5"
          >
            Decline
          </button>
          <button
            type="button"
            onClick={() => {
              void acceptTerms().then(() => {
                navigate("/", { replace: true });
              });
            }}
            className="rounded-2xl bg-ink px-5 py-3 text-sm font-semibold text-white transition hover:bg-ink/90"
          >
            Accept
          </button>
        </div>
      </article>
    </section>
  );
}
