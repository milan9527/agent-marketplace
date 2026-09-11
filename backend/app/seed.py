from sqlalchemy import select

from app.models import Agent, User

DEMO_CATALOG_OWNER = "marketplace-demo-catalog"


def is_demo_profile(agent: Agent) -> bool:
    return agent.owner_id == DEMO_CATALOG_OWNER or agent.wallet.startswith("demo:")


CATALOG = [
    (
        "atlas",
        "Atlas Research",
        "Deep research. Clear answers.",
        "Turn complex questions into structured research briefs, competitive landscapes, and actionable insights with explicit source requirements.",
        "Research",
        ["Deep research", "Industry analysis", "Reports"],
        40000,
        "blue",
        "globe",
        True,
    ),
    (
        "finley",
        "Finley Finance",
        "Your edge in financial analysis.",
        "Analyze company fundamentals, financial metrics, and investment risks from your supplied data. Clear assumptions, no invented live market prices.",
        "Finance",
        ["Stock analysis", "Risk assessment", "Financial modeling"],
        30000,
        "orange",
        "chart",
        True,
    ),
    (
        "codecraft",
        "CodeCraft",
        "Built for your next breakthrough.",
        "An extra pair of expert eyes for code reviews, debugging, API design, and meaningful tests. For developers who care about their craft.",
        "Development",
        ["Code review", "Python", "TypeScript"],
        25000,
        "purple",
        "code",
        True,
    ),
    (
        "quill",
        "Quill Studio",
        "Find the words that move people.",
        "Create brand-aligned articles, campaign copy, and social content. Get original creative directions and ready-to-edit deliverables.",
        "Content",
        ["Copywriting", "SEO", "Multilingual"],
        20000,
        "pink",
        "pen",
        False,
    ),
    (
        "prism",
        "Prism Data",
        "Make your data tell a better story.",
        "Explore structured data, find anomalies, and design data cleaning steps, SQL queries, and visualization plans.",
        "Data",
        ["Data cleaning", "SQL", "Visualization"],
        15000,
        "teal",
        "database",
        False,
    ),
    (
        "relay",
        "Relay Automate",
        "Less busywork. More possibility.",
        "Map repetitive processes into clear automation steps, integration plans, and triggers for smoother cross-platform operations.",
        "Automation",
        ["Workflows", "API integration", "Productivity"],
        20000,
        "green",
        "workflow",
        False,
    ),
    (
        "marcus",
        "Marcus Markets",
        "See the value beyond the numbers.",
        "Explore valuations, compare financial statements, and assess competition with transparent assumptions and data requirements.",
        "Finance",
        ["Value investing", "Valuation", "Financial reports"],
        45000,
        "blue",
        "chart",
        False,
    ),
    (
        "scout",
        "Scout Intelligence",
        "Your next move, better informed.",
        "Investigate markets and competitors, organize product positioning, and uncover differentiated business opportunities.",
        "Research",
        ["Competitive analysis", "Market research", "Strategy"],
        35000,
        "amber",
        "radar",
        False,
    ),
]


def seed_demo(db):
    if db.scalar(select(User).where(User.id == "demo-user")):
        return
    db.add(User(id="demo-user", name="Alex Chen"))
    db.flush()
    for i, (
        slug,
        name,
        tagline,
        description,
        category,
        skills,
        price,
        color,
        icon,
        featured,
    ) in enumerate(CATALOG):
        db.add(
            Agent(
                id=slug,
                owner_id="demo-user",
                name=name,
                tagline=tagline,
                description=description,
                category=category,
                skills=skills,
                price_micros=price,
                wallet=f"0x{i + 1001:040x}",
                color=color,
                icon=icon,
                featured=featured,
            )
        )
    db.commit()


def seed_catalog(db):
    """Add shared demo profiles without overwriting accounts or business data."""
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert

    insert = pg_insert if db.bind.dialect.name == "postgresql" else sqlite_insert
    db.execute(
        insert(User)
        .values(id=DEMO_CATALOG_OWNER, name="Marketplace Demo Catalog")
        .on_conflict_do_nothing(index_elements=["id"])
    )
    added = 0
    for (
        slug,
        name,
        tagline,
        description,
        category,
        skills,
        price,
        color,
        icon,
        featured,
    ) in CATALOG:
        agent_id = f"demo-{slug}"
        existing = db.get(Agent, agent_id)
        if existing and existing.owner_id != DEMO_CATALOG_OWNER:
            raise ValueError("A reserved demo profile ID is already in use")
        result = db.execute(
            insert(Agent)
            .values(
                id=agent_id,
                owner_id=DEMO_CATALOG_OWNER,
                name=name,
                tagline=tagline,
                description=description,
                category=category,
                skills=skills,
                price_micros=price,
                wallet=f"demo:{slug}",
                color=color,
                icon=icon,
                featured=featured,
            )
            .on_conflict_do_nothing(index_elements=["id"])
            .returning(Agent.id)
        )
        added += int(result.scalar_one_or_none() is not None)
    db.commit()
    return {"added": added, "catalog_size": len(CATALOG)}


if __name__ == "__main__":
    import json

    from app.db import session_factory

    with session_factory()() as session:
        print(json.dumps(seed_catalog(session)))
