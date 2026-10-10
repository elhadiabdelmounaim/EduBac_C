---
name: Curriculum media organization
description: User-requested organization of educational files by level and chapter.
---
Organize educational media by school level, then chapter, then separate Cours, Exercices and Sources_IA folders. PDF documents in Cours/Exercices should appear on the lesson page with their original filenames. UTF-8 TXT with literal LaTeX in Sources_IA feeds quiz generation.

**Why:** The user approved this hierarchy, automatic PDF discovery and the faster TXT/LaTeX approach for AI sources.

Quiz generation must let the teacher select one Sources_IA TXT file or all files after selecting a lesson. A specific selection is the only pedagogical source; never silently substitute other lesson content if that file disappears or cannot be read. Keep the existing lesson-content fallback for the all-files option when no TXT is available.

**Why:** The user explicitly requested a file picker, not merely automatic reading of the lesson folder. A selected file must determine the source actually sent to AI.

**How to apply:** Use the actual lessons of each level, not a fixed ten-chapter limit. Preserve existing files and linked paths; do not reorganize unrelated chat or results media. Creating folders does not mean course or exercise documents have been supplied.

For the requested folder naming, use the user's TXT curriculum list as the reference rather than assuming the database titles match.

**Why:** The user clarified that a TXT file in Media contains the intended lesson titles for each level and asked to build the hierarchy from it.

**How to apply:** Locate and read that file first; if absent in the current workspace, ask for its path or upload rather than claiming to have applied its titles.

Level-folder standardization does not authorize creating new curricula or changing existing database level identifiers. The user selected separate empty TCL/TCT resource folders, moving the existing shared common-core resources to TCS, and retaining second-bac mathematics as 2BAC_SM.

**Why:** The requested abbreviation list omitted an existing mathematics level and included common-core branches without separate course data. The user explicitly chose to preserve the existing content without duplication.

**How to apply:** Keep the existing shared curriculum behavior unless separately asked to split it. Do not copy shared lessons into reserved branch folders or remove the mathematics curriculum to match a shorter abbreviation list.
