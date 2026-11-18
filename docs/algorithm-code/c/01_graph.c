/* Weighted directed graph as an adjacency list (linked list of edges per node). */
#include <stdio.h>
#include <stdlib.h>

typedef struct Edge { int to, weight; struct Edge *next; } Edge;
typedef struct { int n; Edge **head; } Graph;

Graph *graph_new(int n) {
    Graph *g = malloc(sizeof *g);
    g->n = n;
    g->head = calloc(n, sizeof *g->head);
    return g;
}

/* Returns 0 on success, -1 if the edge is rejected (as the project's build_graph raises). */
int add_edge(Graph *g, int u, int v, int w) {
    if (u < 0 || v < 0 || u >= g->n || v >= g->n) return -1;   /* unknown node */
    if (u == v) return -1;                                       /* self-loop */
    if (w < 0) return -1;                                        /* Dijkstra needs w >= 0 */
    Edge *e = malloc(sizeof *e), **slot = &g->head[u];
    e->to = v; e->weight = w; e->next = NULL;
    while (*slot) slot = &(*slot)->next;                         /* append: keeps input order */
    *slot = e;
    return 0;
}

Graph *reverse_graph(const Graph *g) {
    Graph *r = graph_new(g->n);
    for (int u = 0; u < g->n; u++)
        for (Edge *e = g->head[u]; e; e = e->next) add_edge(r, e->to, u, e->weight);
    return r;
}

void graph_free(Graph *g) {
    for (int u = 0; u < g->n; u++) {
        Edge *e = g->head[u];
        while (e) { Edge *next = e->next; free(e); e = next; }
    }
    free(g->head); free(g);
}

int main(void) {
    const char *name = "ABCD";
    Graph *g = graph_new(4);
    int edges[][3] = {{0,1,10},{1,0,10},{0,2,20},{2,0,20},{1,2,5},{2,1,5},{2,3,15},{3,2,15}};
    for (int i = 0; i < 8; i++) add_edge(g, edges[i][0], edges[i][1], edges[i][2]);
    for (int u = 0; u < g->n; u++) {
        printf("%c ->", name[u]);
        for (Edge *e = g->head[u]; e; e = e->next) printf(" (%c, %d)", name[e->to], e->weight);
        printf("\n");
    }
    printf("negative weight accepted? %s\n", add_edge(g, 0, 1, -3) == 0 ? "yes" : "no, rejected");
    graph_free(g);
    return 0;
}
