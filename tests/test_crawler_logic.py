from podia_formation.crawler import (
    build_lessons,
    choose_module_title,
    classify_lesson,
    course_slug_from_url,
    course_title,
    is_login_url,
    lesson_from_url,
    pdf_page_count,
    redact,
    renumber,
)

BASE = "https://zonebourse.podia.com/p/courses/investir-en-bourse"


def link(module, mslug, lesson, lslug, text):
    return {"type": "lesson", "href": f"{BASE}/{module}-{mslug}/{lesson}-{lslug}", "text": text}


ITEMS = [
    {"type": "heading", "text": "Investir en bourse"},
    {"type": "heading", "text": "Module 1: Introduction ▾"},
    link(1, "module-1-introduction", 10, "introduction", "Introduction\nTerminé"),
    {"type": "heading", "text": "Module 2: Se lancer ▾"},
    {"type": "heading", "text": "Module 2: Se lancer ▾"},        # doublon (bouton + titre imbriqués)
    link(2, "module-2-se-lancer", 20, "se-lancer", "Se lancer"),
    link(2, "module-2-se-lancer", 21, "les-guides", "Les Guides Zonebourse : Les 10 commandements"),
    link(2, "module-2-se-lancer", 20, "se-lancer", "Se lancer"),   # doublon (version mobile)
    {"type": "heading", "text": "Afficher plus"},                  # bruit sans rapport avec le slug
    link(3, "module-3-les-actions", 30, "les-actions", ""),         # texte vide -> slug
    {"type": "lesson", "href": "https://zonebourse.podia.com/p/courses/autre-formation/9-x/99-y", "text": "Autre"},
]


def test_build_lessons_groups_modules_and_dedupes():
    lessons = build_lessons(ITEMS, "investir-en-bourse")
    assert [l.lesson_id for l in lessons] == ["10", "20", "21", "30"]
    assert [l.index for l in lessons] == [1, 2, 3, 4]
    assert [(l.module_index, l.lesson_index) for l in lessons] == [(1, 1), (2, 1), (2, 2), (3, 1)]
    assert lessons[0].title == "Introduction"                 # « Terminé » retiré
    assert lessons[0].module_title == "Module 1: Introduction"
    assert lessons[1].module_title == "Module 2: Se lancer"
    assert lessons[3].module_title == "Module 3 les actions"  # aucun titre ressemblant : slug
    assert lessons[3].title == "Les actions"
    assert lessons[2].stem == "M02-L02 - Les Guides Zonebourse - Les 10 commandements"


def test_choose_module_title_prefers_closest_matching_heading():
    assert choose_module_title(["Investir en bourse", "Module 4: Les obligations"], "4-module-4-les-obligations") \
        == "Module 4: Les obligations"
    assert choose_module_title(["Menu", "Profil"], "4-module-4-les-obligations") == "Module 4 les obligations"


def test_course_title_and_slug():
    assert course_slug_from_url(f"{BASE}/1-a/2-b") == "investir-en-bourse"
    assert course_slug_from_url("https://x.podia.com/view/courses/demo") == "demo"
    assert course_slug_from_url("https://x.podia.com/login") == ""
    data = {"title": "Se lancer | Investir en bourse", "items": ITEMS}
    assert course_title(data, "investir-en-bourse") == "Investir en bourse"
    assert course_title({"title": "", "items": []}, "investir-en-bourse") == "Investir en bourse"


def test_classify_lesson():
    assert classify_lesson("Se lancer", 40, 1, 0, 0, False, 0) == "video"
    assert classify_lesson("Je teste mes connaissances sur... Les actions", 10, 0, 0, 0, False, 0) == "quiz"
    assert classify_lesson("Bilan", 50, 0, 4, 0, False, 0) == "quiz"
    assert classify_lesson("Fiche Pratique : AAA", 12, 0, 0, 0, False, 1) == "fichier"
    assert classify_lesson("Décryptage", 900, 0, 0, 0, False, 0) == "article"
    assert classify_lesson("Vide", 3, 0, 0, 0, False, 0) == "vide"


def test_lesson_from_url_and_renumber():
    lessons = build_lessons(ITEMS, "investir-en-bourse")
    extra = lesson_from_url(f"{BASE}/2-module-2-se-lancer/22-decryptage-le-plus-tot#top", "Module 2: Se lancer")
    assert extra.lesson_id == "22" and extra.url.endswith("22-decryptage-le-plus-tot")
    lessons.insert(3, extra)
    renumber(lessons)
    assert [(l.lesson_id, l.module_index, l.lesson_index) for l in lessons] == [
        ("10", 1, 1), ("20", 2, 1), ("21", 2, 2), ("22", 2, 3), ("30", 3, 1)]
    assert lesson_from_url("https://x/p/courses/y") is None


def test_pdf_page_count_and_redact():
    pdf = b"<< /Type /Pages /Count 2 >> << /Type /Page >> << /Type/Page >>"
    assert pdf_page_count(pdf) == 2
    text = '<meta name="csrf-token" content="abc123"> src="https://h/eyJhbGciOi.eyJzdWIiOi.c2ln/iframe"'
    out = redact(text)
    assert "abc123" not in out and "eyJzdWIiOi" not in out


def test_navigation_links_never_become_lesson_titles():
    from podia_formation.crawler import LESSON_URL_RE

    items = [
        link(2, "module-2-se-lancer", 20, "se-lancer", "Continuer"),       # bouton de navigation
        link(2, "module-2-se-lancer", 20, "se-lancer", "Se lancer"),       # vraie entrée du sommaire
    ]
    lessons = build_lessons(items, "investir-en-bourse")
    assert [l.title for l in lessons] == ["Se lancer"]
    assert LESSON_URL_RE.search("/p/courses/c/1-m/2-l/completions") is None     # lien « marquer terminé »


def test_pick_and_replace_lesson_titles():
    from podia_formation.crawler import better_title, pick_lesson_title

    # Le h1 de la barre latérale (titre de la formation) ne doit pas l'emporter sur celui de la leçon.
    assert pick_lesson_title(["Investir en bourse", "Se lancer"], "Se lancer", "se-lancer") == "Se lancer"
    assert pick_lesson_title(["Investir en bourse"], "", "se-lancer") == ""
    assert better_title("Decryptage bonus", "Décryptage : bonus caché", "decryptage-bonus")
    assert not better_title("Les Guides Zonebourse", "Investir en bourse", "les-guides")
    assert better_title("Continuer", "Les actions", "les-actions")


def test_redact_masks_personal_data():
    html = ('<script>Podia.Customer = {"id": 1, "email": "moi@exemple.fr", "first_name": "Val"};</script>'
            '<input name="authenticity_token" value="XYZ"> contact: moi@exemple.fr cus_ABC123')
    out = redact(html)
    for secret in ("moi@exemple.fr", "Val", "XYZ", "cus_ABC123"):
        assert secret not in out


def test_pdf_page_count_with_compressed_objects():
    # Pages rangées dans un flux compressé : seul le /Count du dictionnaire /Pages est lisible.
    data = b"%PDF-1.5 << /Type /Pages /Kids [3 0 R] /Count 5 >> stream x\x9c... endstream"
    assert pdf_page_count(data) == 5


def test_module_numbers_follow_the_course():
    lessons = build_lessons(ITEMS, "investir-en-bourse")
    for l in lessons:
        l.module_title = {"1": "Module 2: Se lancer", "2": "Module 7 la diversification", "3": "Module 8 terminologie"}[l.module_id]
    renumber(lessons)
    assert [l.module_index for l in lessons] == [2, 7, 7, 8]
    lessons[0].module_title = "Bonus"                     # un module sans numéro : numérotation dans l'ordre
    renumber(lessons)
    assert [l.module_index for l in lessons] == [1, 2, 2, 3]


def test_lesson_titles_are_never_taken_for_a_login_page():
    site = "https://zonebourse.podia.com"
    lesson = (site + "/p/courses/investir-en-bourse/341500-module-15-selection/974000-"
              "fiche-pratique-les-15-points-a-verifier-quand-on-selectionne-un-titre")
    assert not is_login_url(lesson)                               # cas réel : « a-verifier »
    for slug in ("signal-d-achat", "une-session-de-bourse", "l-auteur-authentique", "design", "connexion-au-courtier"):
        assert not is_login_url(f"{site}/p/courses/investir-en-bourse/1-module/2-{slug}")
    assert not is_login_url(site + "/p/home")
    for path in ("/login", "/login?return_to=%2Fp%2Fhome", "/users/sign_in", "/p/login", "/two_factor/new",
                 "/password/new", "/sessions/new", "/auth/callback", "/login/verify"):
        assert is_login_url(site + path), path
