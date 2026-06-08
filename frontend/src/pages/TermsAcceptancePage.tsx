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
      <article className="">
        <h2 className="font-display text-2xl">Terms and Policies</h2>
        <p className="mt-2 text-sm text-sand/65">
          Please review and accept the terms and policies to continue.
        </p>

        <div className="surface-muted mt-4 max-h-[50vh] overflow-y-auto p-5">
          {isTermsEnabled && termsSettings.terms_content ? (
            <MarkdownRenderer content={termsSettings.terms_content} />
          ) : (
            <p className="text-sm text-sand/65">No terms and policies content has been configured.</p>
          )}
        </div>

        <div className="mt-6 flex items-center justify-end gap-3">
          <button
            type="button"
            onClick={() => {
              declineTerms();
            }}
            className="btn-secondary px-5 py-3 text-sm font-semibold text-sand transition hover:border-white/20 hover:bg-white/10"
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
            className=" bg-sand px-5 py-3 text-sm font-semibold text-canvas transition hover:bg-sand/80"
          >
            Accept
          </button>
        </div>
      </article>
    </section>
  );
}
