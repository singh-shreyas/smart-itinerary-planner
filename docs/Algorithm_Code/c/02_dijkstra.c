/* Dijkstra with a binary min-heap (lazy deletion), all pairs, and path rebuild. */
#include <stdio.h>
#include <limits.h>

#define N 4
#define INF INT_MAX
#define MAXE 64

typedef struct { int to, w; } Arc;
Arc adj[N][N]; int deg[N];

typedef struct { int d, v; } Node;               /* heap entry: (distance, vertex) */
Node heap[MAXE]; int hsize;

void push(int d, int v) {
    int i = hsize++;
    heap[i] = (Node){d, v};
    while (i > 0 && heap[(i - 1) / 2].d > heap[i].d) {       /* sift up */
        Node t = heap[i]; heap[i] = heap[(i - 1) / 2]; heap[(i - 1) / 2] = t;
        i = (i - 1) / 2;
    }
}

Node pop(void) {
    Node top = heap[0];
    heap[0] = heap[--hsize];
    int i = 0;
    for (;;) {                                                 /* sift down */
        int l = 2 * i + 1, r = l + 1, m = i;
        if (l < hsize && heap[l].d < heap[m].d) m = l;
        if (r < hsize && heap[r].d < heap[m].d) m = r;
        if (m == i) break;
        Node t = heap[i]; heap[i] = heap[m]; heap[m] = t;
        i = m;
    }
    return top;
}

void dijkstra(int src, int dist[N], int prev[N]) {
    for (int v = 0; v < N; v++) { dist[v] = INF; prev[v] = -1; }
    dist[src] = 0; hsize = 0;
    push(0, src);
    while (hsize > 0) {
        Node top = pop();
        if (top.d > dist[top.v]) continue;                     /* stale entry */
        for (int k = 0; k < deg[top.v]; k++) {                 /* relax edges */
            int v = adj[top.v][k].to, nd = top.d + adj[top.v][k].w;
            if (nd < dist[v]) { dist[v] = nd; prev[v] = top.v; push(nd, v); }
        }
    }
}

void print_path(const int prev[N], int src, int t, const char *name) {
    int path[N], len = 0;
    if (t != src && prev[t] == -1) { printf("unreachable\n"); return; }
    for (int v = t; v != -1; v = prev[v]) path[len++] = v;
    for (int i = len - 1; i >= 0; i--) printf("%c%s", name[path[i]], i ? " -> " : "\n");
}

void link(int u, int v, int w) { adj[u][deg[u]++] = (Arc){v, w}; adj[v][deg[v]++] = (Arc){u, w}; }

int main(void) {
    const char *name = "ABCD";
    link(0, 1, 10); link(0, 2, 20); link(1, 2, 5); link(2, 3, 15);
    int dist[N][N], prev[N][N];
    for (int s = 0; s < N; s++) {                              /* all pairs: one run per source */
        dijkstra(s, dist[s], prev[s]);
        printf("%c", name[s]);
        for (int t = 0; t < N; t++) printf(" %3d", dist[s][t]);
        printf("\n");
    }
    printf("path A->D: ");
    print_path(prev[0], 0, 3, name);
    return 0;
}
