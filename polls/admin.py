from django.contrib import admin
from polls.models import Poll, PollOption, PollVoter, Vote, MemberFeedback


class PollOptionInline(admin.TabularInline):
    model = PollOption
    extra = 2
    fields = ('text', 'description', 'votes_count', 'display_order')


@admin.register(Poll)
class PollAdmin(admin.ModelAdmin):
    list_display = ('title', 'poll_type', 'start_date', 'end_date', 'status', 'is_secret_ballot', 'total_votes')
    list_filter = ('poll_type', 'status', 'is_secret_ballot')
    search_fields = ('title', 'description')
    inlines = [PollOptionInline]


@admin.register(PollVoter)
class PollVoterAdmin(admin.ModelAdmin):
    list_display = ('poll', 'member', 'voted_at')
    list_filter = ('poll',)
    search_fields = ('member__name', 'member__membership_id', 'poll__title')


@admin.register(Vote)
class VoteAdmin(admin.ModelAdmin):
    list_display = ('poll', 'option', 'member', 'voted_at')
    list_filter = ('poll',)


@admin.register(MemberFeedback)
class MemberFeedbackAdmin(admin.ModelAdmin):
    list_display = ('subject', 'member', 'category', 'rating', 'status', 'is_public', 'created_at')
    list_filter = ('category', 'status', 'is_public', 'rating')
    search_fields = ('subject', 'message', 'member__name', 'member__membership_id')
