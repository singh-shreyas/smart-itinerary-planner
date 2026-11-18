/* Attraction score 0..100: 0.5 * rating/5 + 0.3 * popularity + 0.2 * interest match. */
#include <stdio.h>
#include <string.h>
#include <math.h>

#define W_RATING 0.5
#define W_POPULARITY 0.3
#define W_INTEREST 0.2
#define RATING_PRIOR 4.0
#define NO_RATING -1.0

/* tiny category tree: child -> parent */
const char *child[]  = {"street-food", "fort"};
const char *parent[] = {"food",        "history"};

const char *parent_of(const char *c) {
    for (int i = 0; i < 2; i++) if (strcmp(child[i], c) == 0) return parent[i];
    return NULL;
}

/* 1 if the category, or any ancestor, is the interest (matching flows upward only) */
int matches(const char *category, const char *interest) {
    for (const char *c = category; c; c = parent_of(c))
        if (strcmp(c, interest) == 0) return 1;
    return 0;
}

int score(double rating, double popularity, const char *category, const char *interest) {
    if (rating == NO_RATING) rating = RATING_PRIOR;            /* neutral prior */
    int match = matches(category, interest);
    double value = W_RATING * (rating / 5) + W_POPULARITY * popularity + W_INTEREST * match;
    return (int)lround(100 * value);
}

int main(void) {
    printf("%d\n", score(4.6, 0.8, "fort", "history"));
    printf("%d\n", score(4.6, 0.8, "fort", "food"));
    printf("%d\n", score(NO_RATING, 0.5, "street-food", "food"));
    return 0;
}
