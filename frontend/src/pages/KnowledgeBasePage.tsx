import { useEffect, useRef, useState, type FormEvent } from "react";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
import Modal from "../components/ui/Modal";
import CodeEditor from "../components/ui/CodeEditor";
import {
  createKbDocument,
  deleteKbDocument,
  fetchKbDocuments,
  updateKbDocument,
  fetchKbCategories,
  createKbCategory,
  updateKbCategory,
  deleteKbCategory,
} from "../lib/api";
import type { KnowledgeBaseDocumentRecord, KnowledgeBaseCategoryRecord } from "../lib/records";

const MAX_CONTENT_LENGTH = 10240;

type DraftMode = "idle" | "creating" | "editing";

export default function KnowledgeBasePage() {
  const { token } = useAuth();
  const { showError, showSuccess } = useToast();
  const [documents, setDocuments] = useState<KnowledgeBaseDocumentRecord[]>([]);
  const [categories, setCategories] = useState<KnowledgeBaseCategoryRecord[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [draftMode, setDraftMode] = useState<DraftMode>("idle");
  const [editingId, setEditingId] = useState<number | null>(null);
  const [draftTitle, setDraftTitle] = useState("");
  const [draftContent, setDraftContent] = useState("");
  const [draftCategoryId, setDraftCategoryId] = useState<number | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [isDeleting, setIsDeleting] = useState<number | null>(null);
  const [selectedCategoryId, setSelectedCategoryId] = useState<number | null>(null);
  const [isCategoryModalOpen, setIsCategoryModalOpen] = useState(false);
  const [isCategoryCreateModalOpen, setIsCategoryCreateModalOpen] = useState(false);
  const [editingCategoryId, setEditingCategoryId] = useState<number | null>(null);
  const [categoryName, setCategoryName] = useState("");
  const [isDeletingCategory, setIsDeletingCategory] = useState<number | null>(null);
  const [openMenuId, setOpenMenuId] = useState<string | null>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!token) return;
    void loadAll(token);
  }, [token]);

  useEffect(() => {
    if (!token) return;
    void loadDocuments(token);
  }, [selectedCategoryId]);

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setOpenMenuId(null);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  async function loadAll(activeToken: string) {
    setIsLoading(true);
    try {
      const [docs, cats] = await Promise.all([
        fetchKbDocuments<KnowledgeBaseDocumentRecord[]>(activeToken, selectedCategoryId ?? undefined),
        fetchKbCategories<KnowledgeBaseCategoryRecord[]>(activeToken),
      ]);
      setDocuments(docs);
      setCategories(cats);
    } catch (error) {
      showError(error instanceof Error ? error.message : "Failed to load knowledge base data");
    } finally {
      setIsLoading(false);
    }
  }

  async function loadDocuments(activeToken: string) {
    try {
      const docs = await fetchKbDocuments<KnowledgeBaseDocumentRecord[]>(activeToken, selectedCategoryId ?? undefined);
      setDocuments(docs);
    } catch (error) {
      showError(error instanceof Error ? error.message : "Failed to load documents");
    }
  }

  async function loadCategories(activeToken: string) {
    try {
      const cats = await fetchKbCategories<KnowledgeBaseCategoryRecord[]>(activeToken);
      setCategories(cats);
    } catch (error) {
      showError(error instanceof Error ? error.message : "Failed to load categories");
    }
  }

  function startCreate(preselectedCategoryId?: number) {
    setDraftMode("creating");
    setDraftTitle("");
    setDraftContent("");
    if (preselectedCategoryId !== undefined) {
      setDraftCategoryId(preselectedCategoryId);
    } else {
      const defaultCat = categories.find((c) => c.is_default);
      setDraftCategoryId(defaultCat ? defaultCat.id : null);
    }
    setEditingId(null);
  }

  function startEdit(doc: KnowledgeBaseDocumentRecord) {
    setDraftMode("editing");
    setDraftTitle(doc.title);
    setDraftContent(doc.content);
    setDraftCategoryId(doc.category_id);
    setEditingId(doc.id);
  }

  function cancelDraft() {
    setDraftMode("idle");
    setDraftTitle("");
    setDraftContent("");
    setDraftCategoryId(null);
    setEditingId(null);
  }

  async function saveDraft(e: FormEvent) {
    e.preventDefault();
    if (!token || !draftTitle.trim() || !draftCategoryId) return;

    setIsSaving(true);
    try {
      const payload = { title: draftTitle.trim(), content: draftContent, category_id: draftCategoryId };
      if (draftMode === "creating") {
        await createKbDocument(payload, token);
        showSuccess("Document created.");
      } else if (editingId !== null) {
        await updateKbDocument(editingId, payload, token);
        showSuccess("Document updated.");
      }
      setDraftMode("idle");
      setDraftTitle("");
      setDraftContent("");
      setDraftCategoryId(null);
      setEditingId(null);
      if (token) await loadDocuments(token);
    } catch (error) {
      showError(error instanceof Error ? error.message : "Failed to save document");
    } finally {
      setIsSaving(false);
    }
  }

  async function handleDelete(docId: number) {
    if (!token) return;
    if (!window.confirm("Delete this document? This cannot be undone.")) return;

    setIsDeleting(docId);
    try {
      await deleteKbDocument(docId, token);
      showSuccess("Document deleted.");
      if (editingId === docId) cancelDraft();
      await loadDocuments(token);
    } catch (error) {
      showError(error instanceof Error ? error.message : "Failed to delete document");
    } finally {
      setIsDeleting(null);
    }
  }

  const openEditCategory = (cat: KnowledgeBaseCategoryRecord) => {
    setEditingCategoryId(cat.id);
    setCategoryName(cat.name);
    setIsCategoryModalOpen(true);
  };

  const openCreateCategory = () => {
    setEditingCategoryId(null);
    setCategoryName("");
    setIsCategoryCreateModalOpen(true);
  };

  async function handleSaveCategory(e: FormEvent) {
    e.preventDefault();
    if (!token || !categoryName.trim()) return;

    try {
      if (editingCategoryId !== null) {
        await updateKbCategory(editingCategoryId, { name: categoryName.trim() }, token);
        showSuccess("Category updated.");
      } else {
        await createKbCategory({ name: categoryName.trim() }, token);
        showSuccess("Category created.");
      }
      setIsCategoryModalOpen(false);
      setIsCategoryCreateModalOpen(false);
      setCategoryName("");
      setEditingCategoryId(null);
      if (token) await loadCategories(token);
    } catch (error) {
      showError(error instanceof Error ? error.message : "Failed to save category");
    }
  }

  async function handleDeleteCategory(catId: number) {
    if (!token) return;
    if (!window.confirm("Delete this category? Documents in this category will become uncategorized.")) return;

    setIsDeletingCategory(catId);
    try {
      await deleteKbCategory(catId, token);
      showSuccess("Category deleted.");
      if (selectedCategoryId === catId) {
        setSelectedCategoryId(null);
      }
      if (token) await loadAll(token);
    } catch (error) {
      showError(error instanceof Error ? error.message : "Failed to delete category");
    } finally {
      setIsDeletingCategory(null);
    }
  }

  const contentPreview = (content: string, maxLength: number = 150): string => {
    if (content.length <= maxLength) return content;
    return content.slice(0, maxLength) + "...";
  };

  const getCategoryName = (catId: number | null): string | null => {
    if (catId === null) return null;
    return categories.find((c) => c.id === catId)?.name ?? null;
  };

  const getDocumentCount = (catId: number | null): number => {
    if (catId === null) return 0;
    return documents.filter((d) => d.category_id === catId).length;
  };

  return (
    <div className="grid gap-4 lg:grid-cols-[260px_1fr] lg:gap-5">
      {/* Sidebar - Categories */}
      <aside className="surface p-4 lg:order-1 lg:sticky lg:top-[72px] lg:max-h-[calc(100vh-88px)] lg:overflow-y-auto">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="font-display text-base">Categories</h2>
          <button
            type="button"
            onClick={openCreateCategory}
            className=" bg-sand px-2.5 py-1 text-[13px] font-semibold text-canvas transition hover:bg-sand/80"
          >
            + Add
          </button>
        </div>

        <div ref={menuRef} className="space-y-0.5">
          <div className="relative overflow-visible">
            <button
              type="button"
              onClick={() => {
                if (draftMode !== "idle") cancelDraft();
                setSelectedCategoryId(null);
                setOpenMenuId("all");
              }}
              className={`mb-1 flex w-full items-center justify-between gap-2  px-2.5 py-2 text-left text-sm transition ${
                selectedCategoryId === null
                  ? "bg-sand text-canvas"
                  : "text-sand/70 hover:bg-white/10"
              }`}
            >
              <div className="flex items-center gap-2">
                <i className="bi bi-collection text-[14px]"></i>
                <span className="font-medium">All</span>
              </div>
              <button
                type="button"
                onClick={(e) => { e.stopPropagation(); setOpenMenuId(openMenuId === "all" ? null : "all"); }}
                className=" p-1 transition hover:bg-white/20"
              >
                <i className="bi bi-three-dots-vertical text-[14px]"></i>
              </button>
            </button>

            {openMenuId === "all" && (
              <div className="absolute right-2 z-50 mt-1 w-40  surface py-1 shadow-lg">
                <button
                  type="button"
                  onMouseDown={(e) => e.stopPropagation()}
                  onClick={() => { setOpenMenuId(null); startCreate(); }}
                  className="flex w-full items-center gap-2 px-3 py-2 text-sm text-sand/70 transition hover:bg-white/10"
                >
                  <i className="bi bi-plus-lg text-[14px]"></i>
                  Add Document
                </button>
              </div>
            )}
          </div>

          {categories.length === 0 ? (
            <p className="px-2.5 py-2 text-xs text-sand/40">
              No categories yet.
            </p>
          ) : (
            categories.map((cat) => (
              <button
                key={cat.id}
                type="button"
                onClick={() => {
                  if (draftMode !== "idle") cancelDraft();
                  setSelectedCategoryId(selectedCategoryId === cat.id ? null : cat.id);
                }}
                className={`relative flex w-full items-center justify-between gap-2 overflow-visible  px-2.5 py-2 text-left text-sm transition ${
                  selectedCategoryId === cat.id
                    ? "bg-sand text-canvas"
                    : "text-sand/70 hover:bg-white/10"
                }`}
              >
                <div className="flex items-center gap-2">
                  <i className={`bi bi-folder text-[14px] ${
                    selectedCategoryId === cat.id ? "text-white/70" : "text-sand/35"
                  }`}></i>
                  <span className="text-sm">{cat.name}</span>
                  <span className={` px-1.5 py-0.5 text-[10px] font-medium ${
                    selectedCategoryId === cat.id
                      ? "bg-white/20 text-white/80"
                      : "bg-black/10 text-sand/50"
                  }`}>{getDocumentCount(cat.id)}</span>
                </div>
                <button
                  type="button"
                  onClick={(e) => { e.stopPropagation(); setOpenMenuId(openMenuId === `cat-${cat.id}` ? null : `cat-${cat.id}`); }}
                  className=" p-1 transition hover:bg-white/20"
                >
                  <i className="bi bi-three-dots-vertical text-[14px]"></i>
                </button>

                {openMenuId === `cat-${cat.id}` && (
                  <div className="absolute right-2 z-50 mt-1 w-40  surface py-1 shadow-lg">
                    <button
                      type="button"
                      onMouseDown={(e) => e.stopPropagation()}
                      onClick={() => { setOpenMenuId(null); startCreate(cat.id); }}
                      className="flex w-full items-center gap-2 px-3 py-2 text-sm text-sand/70 transition hover:bg-white/10"
                    >
                      <i className="bi bi-plus-lg text-[14px]"></i>
                      Add Document
                    </button>
                    <button
                      type="button"
                      onMouseDown={(e) => e.stopPropagation()}
                      onClick={() => { setOpenMenuId(null); openEditCategory(cat); }}
                      className="flex w-full items-center gap-2 px-3 py-2 text-sm text-sand/70 transition hover:bg-white/10"
                    >
                      <i className="bi bi-pencil text-[14px]"></i>
                      Edit
                    </button>
                    {!cat.is_default && getDocumentCount(cat.id) === 0 && (
                      <button
                        type="button"
                        onMouseDown={(e) => e.stopPropagation()}
                        onClick={() => { setOpenMenuId(null); handleDeleteCategory(cat.id); }}
                        disabled={isDeletingCategory === cat.id}
                        className="flex w-full items-center gap-2 px-3 py-2 text-sm text-red-600 transition hover:bg-red-50 disabled:opacity-50"
                      >
                        <i className="bi bi-trash text-[14px]"></i>
                        {isDeletingCategory === cat.id ? "Deleting..." : "Delete"}
                      </button>
                    )}
                  </div>
                )}
              </button>
            ))
          )}
        </div>
      </aside>

      {/* Main content area */}
      <div className="grid gap-4 lg:order-2">
        {/* Draft form */}
        {(draftMode === "creating" || draftMode === "editing") && (
          <article className="surface p-5">
            <form onSubmit={saveDraft}>
              <div className="mb-3 flex items-center justify-between">
                <h2 className="font-display text-lg">{draftMode === "creating" ? "Add Document" : "Edit Document"}</h2>
              </div>
              <div className="grid gap-3">
                <div>
                  <label className="mb-1 block text-sm font-medium text-sand/70">Category</label>
                  <select
                    value={draftCategoryId ?? ""}
                    onChange={(e) => setDraftCategoryId(Number(e.target.value))}
                    className="w-full  field px-3 py-2 text-sm"
                    required
                  >
                    <option value="" disabled>
                      Select a category
                    </option>
                    {categories.map((cat) => (
                      <option key={cat.id} value={cat.id}>
                        {cat.name}{cat.is_default ? " (Default)" : ""}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="mb-1 block text-sm font-medium text-sand/70">Title</label>
                  <input
                    type="text"
                    value={draftTitle}
                    onChange={(e) => setDraftTitle(e.target.value)}
                    className="w-full  field px-3 py-2 text-sm"
                    placeholder="Document title"
                    autoFocus
                    required
                  />
                </div>
                <CodeEditor
                  value={draftContent}
                  onChange={setDraftContent}
                  placeholder="Write your markdown content here..."
                  maxLength={MAX_CONTENT_LENGTH}
                />
                <div className="flex gap-2">
                  <button
                    type="submit"
                    disabled={isSaving || !draftTitle.trim()}
                    className=" bg-sand px-4 py-2 text-sm font-semibold text-canvas transition hover:bg-sand/80 disabled:opacity-50"
                  >
                    {isSaving ? "Saving..." : draftMode === "creating" ? "Create" : "Update"}
                  </button>
                  <button
                    type="button"
                    onClick={cancelDraft}
                    className=" border border-white/15 px-4 py-2 text-sm font-semibold text-sand/70 transition hover:bg-white/10"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            </form>
          </article>
        )}

        {/* Document list */}
        {draftMode === "idle" && (
        <article className="surface p-5">
          <div className="mb-4 flex items-center gap-2 text-sm">
            <span className="font-display text-base">Documents</span>
            {selectedCategoryId !== null && (
              <>
                <i className="bi bi-chevron-right text-[10px] text-sand/30"></i>
                <span className="font-medium text-sand/70">
                  {categories.find((c) => c.id === selectedCategoryId)?.name}
                </span>
              </>
            )}
          </div>

          {isLoading ? (
            <p className="py-8 text-center text-sm text-sand/45">Loading...</p>
          ) : documents.length === 0 ? (
            <p className="py-8 text-center text-sm text-sand/45">
              No documents yet. Use the menu icon next to a category to add one.
            </p>
          ) : (
            <div className="grid gap-3">
              {documents.map((doc) => (
                <div
                  key={doc.id}
                  className="relative  border border-white/10 bg-white/10 p-4 transition hover:bg-white/20"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex-1">
                      <div className="flex items-center gap-2">
                        <h3 className="font-semibold text-sand/80">{doc.title}</h3>
                        {getCategoryName(doc.category_id) && (
                          <span className=" bg-black/10 px-2 py-0.5 text-[11px] font-medium text-sand/60">
                            {getCategoryName(doc.category_id)}
                          </span>
                        )}
                      </div>
                      <p className="mt-1 text-sm text-sand/60">
                        {contentPreview(doc.content)}
                      </p>
                      <p className="mt-1 text-xs text-sand/40">
                        Updated: {doc.updated_at ? new Date(doc.updated_at).toLocaleDateString() : "N/A"}
                      </p>
                    </div>
                    <div className="relative shrink-0">
                      <button
                        type="button"
                        onClick={(e) => { e.stopPropagation(); setOpenMenuId(openMenuId === `doc-${doc.id}` ? null : `doc-${doc.id}`); }}
                        className=" border border-white/15 p-1.5 text-xs text-sand/70 transition hover:bg-white/10"
                      >
                        <i className="bi bi-three-dots-vertical"></i>
                      </button>
                      {openMenuId === `doc-${doc.id}` && (
                        <div className="absolute right-0 z-50 mt-1 w-40  surface py-1 shadow-lg">
                          <button
                            type="button"
                            onMouseDown={(e) => e.stopPropagation()}
                            onClick={() => { setOpenMenuId(null); startEdit(doc); }}
                            className="flex w-full items-center gap-2 px-3 py-2 text-sm text-sand/70 transition hover:bg-white/10"
                          >
                            <i className="bi bi-pencil text-[14px]"></i>
                            Edit
                          </button>
                          <button
                            type="button"
                            onMouseDown={(e) => e.stopPropagation()}
                            onClick={() => { setOpenMenuId(null); handleDelete(doc.id); }}
                            disabled={isDeleting === doc.id}
                            className="flex w-full items-center gap-2 px-3 py-2 text-sm text-red-600 transition hover:bg-red-50 disabled:opacity-50"
                          >
                            <i className="bi bi-trash text-[14px]"></i>
                            {isDeleting === doc.id ? "Deleting..." : "Delete"}
                          </button>
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </article>
        )}
      </div>

      {/* Edit category modal */}
      <Modal open={isCategoryModalOpen} onClose={() => setIsCategoryModalOpen(false)} labelledBy="category-edit-title" panelClassName="max-w-md">
        <article className="p-5 sm:p-6">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 id="category-edit-title" className="font-display text-2xl">Edit Category</h2>
            </div>
            <button className="btn-secondary px-4 py-2 text-sm font-semibold text-sand" type="button" onClick={() => setIsCategoryModalOpen(false)}>
              Close
            </button>
          </div>
          <form className="mt-5 grid gap-3" onSubmit={handleSaveCategory}>
            <label className="grid gap-1 text-sm text-sand/70">
              Category Name
              <input
                className=" field px-3 py-2 text-sm"
                value={categoryName}
                onChange={(e) => setCategoryName(e.target.value)}
                autoFocus
                required
              />
            </label>
            <button className=" bg-sand px-4 py-2 text-sm font-semibold text-canvas disabled:cursor-not-allowed disabled:opacity-60" type="submit" disabled={!categoryName.trim()}>
              Update Category
            </button>
          </form>
        </article>
      </Modal>

      {/* Create category modal */}
      <Modal open={isCategoryCreateModalOpen} onClose={() => setIsCategoryCreateModalOpen(false)} labelledBy="category-create-title" panelClassName="max-w-md">
        <article className="p-5 sm:p-6">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 id="category-create-title" className="font-display text-2xl">Add Category</h2>
            </div>
            <button className="btn-secondary px-4 py-2 text-sm font-semibold text-sand" type="button" onClick={() => setIsCategoryCreateModalOpen(false)}>
              Close
            </button>
          </div>
          <form className="mt-5 grid gap-3" onSubmit={handleSaveCategory}>
            <label className="grid gap-1 text-sm text-sand/70">
              Category Name
              <input
                className=" field px-3 py-2 text-sm"
                value={categoryName}
                onChange={(e) => setCategoryName(e.target.value)}
                autoFocus
                required
              />
            </label>
            <button className=" bg-sand px-4 py-2 text-sm font-semibold text-canvas disabled:cursor-not-allowed disabled:opacity-60" type="submit" disabled={!categoryName.trim()}>
              Create Category
            </button>
          </form>
        </article>
      </Modal>
    </div>
  );
}
