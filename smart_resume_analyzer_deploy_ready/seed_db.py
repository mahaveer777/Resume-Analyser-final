import sqlite3

DB_FILE = 'roles.db'

INITIAL_ROLES = {
    "Data Analyst": "python, sql, excel, tableau, power bi, pandas, numpy, statistics, data visualization, sql queries",
    "AI Engineer": "python, pytorch, tensorflow, machine learning, deep learning, llms, LangChain, transformers, NLP, docker",
    "Cloud Engineer": "aws, azure, gcp, terraform, docker, kubernetes, linux, CI/CD, bash, networking",
    "Web Developer": "javascript, html, css, react, node.js, typescript, git, rest api, tailwind, mongodb",
    "Software Engineer": "python, java, c++, data structures, algorithms, git, sql, oop, system design",
    "Data Scientist": "python, pandas, numpy, scikit-learn, sql, machine learning, statistics, r, deep learning",
    "DevOps Engineer": "docker, kubernetes, aws, ci/cd, linux, terraform, ansible, python, bash, prometheus",
    "UI/UX Designer": "figma, wireframing, prototyping, user research, adobe xd, css, html, user testing",
    "Cybersecurity Analyst": "siem, firewall, network security, vulnerability assessment, wireshark, penetration testing, linux, incident response",
    "Product Manager": "agile, scrum, roadmap, user stories, stakeholder management, market research, data analysis, product strategy",
    "Full Stack Developer": "javascript, react, node.js, express, mongodb, sql, html, css, git, docker",
    "Backend Engineer": "python, node.js, django, fastAPI, sql, postgresql, redis, docker, rest api, microservices",
    "Frontend Engineer": "javascript, typescript, react, next.js, html, css, tailwind, redux, jest, git",
    "Mobile App Developer": "flutter, dart, react native, swift, kotlin, mobile UI, firebase, git, REST APIs",
    "Database Administrator": "sql, postgresql, mysql, oracle, database tuning, backup, replication, security, linux, scripting"
}

def seed():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS roles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role_name TEXT UNIQUE NOT NULL,
            skills TEXT NOT NULL
        )
    ''')
    for role, skills in INITIAL_ROLES.items():
        try:
            cursor.execute("INSERT INTO roles (role_name, skills) VALUES (?, ?)", (role, skills))
        except sqlite3.IntegrityError:
            pass # Skip if role already exists
    conn.commit()
    conn.close()
    print("Successfully seeded 15 job roles into roles.db!")

if __name__ == '__main__':
    seed()