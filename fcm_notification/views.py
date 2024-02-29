import logging

from django.contrib.auth.decorators import login_required
from django.contrib.auth.decorators import permission_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404
from django.shortcuts import redirect, reverse
from django.shortcuts import render
from django.views import View
from django.views.generic import ListView

from fcm_notification.forms import (
    SendPushMessageForm, CreateBulkMessageForm, EditMessageForm, SearchMessageForm, SearchBulkMessageForm,
    SearchBulkMessageReceiverForm
)
from fcm_notification.models import (
    PushMessage, BulkNotificationFile, BulkNotificationRequest, BulkNotificationReceiver, ReceiverType,
    BulkNotificationSendRequest, BulkNotificationSchedule
)
from fcm_notification.serializers import SendBulkNotificationSerializer
from fcm_notification.services.bulk_service import schedule_bulk_notification
from fcm_notification.services.notification_service import send_push_message
from fcm_notification.tasks import parse_bulk_notification_file

logger = logging.getLogger('notification_views')


@login_required
@permission_required('notification.add_pushmessage')
def create_push_message(request):
    return render(request, 'notification/create.html')


@login_required
def send_message_success(request, message_id):
    mobile = request.GET.get('mobile')
    return render(request, 'notification/sent.html', {
        'message_id': message_id, 'mobile': mobile
    })


@login_required
@permission_required('notification.add_messagedeliverylog')
def send_message(request, message_id):
    if request.method == 'POST':
        form = SendPushMessageForm(data=request.POST, files=request.FILES)
        if form.is_valid():
            user_name = request.user.username
            mobile_number = form.cleaned_data['mobile']
            send_push_message(message_id, mobile_number, user_name)
            return redirect('{}?mobile={}'.format(
                reverse('message_sent', args=[message_id, ]), mobile_number
            ))
    else:
        form = SendPushMessageForm()

    try:
        push_message = PushMessage.objects.get(pk=message_id)
    except PushMessage.DoesNotExist:
        raise Http404("Message does not exist")
    return render(request, 'notification/send.html', {'msg': push_message, 'form': form})


@login_required
@permission_required('notification.add_bulknotificationrequest')
def create_bulk_message_request(request):
    if request.method == 'POST':
        form = CreateBulkMessageForm(data=request.POST, files=request.FILES)
        if form.is_valid():
            # create the request
            bulk_notification_request = form.save(commit=False)
            bulk_notification_request.created_by = request.user.username
            bulk_notification_request.status = 1
            bulk_notification_request.save()

            # upload a file with receiver mobile numbers
            bulk_notification_file = BulkNotificationFile.objects.create(
                request=bulk_notification_request, uploaded_file=request.FILES['receiver_list']
            )
            parse_bulk_notification_file.delay(bulk_notification_file.pk)
            return redirect('bulk_message_send_request', request_id=bulk_notification_request.pk)
    else:
        form = CreateBulkMessageForm()

    return render(request, 'notification/bulk_push/create.html', {'form': form})


@login_required
@permission_required('notification.add_pushmessage')
def edit_message(request, message_id):
    try:
        push_message = PushMessage.objects.get(pk=message_id)
    except PushMessage.DoesNotExist:
        raise Http404()

    if request.method == 'POST':
        form = EditMessageForm(data=request.POST, instance=push_message)
        if form.is_valid():
            form.save()
            return redirect('send_message', message_id=message_id)
    else:
        form = EditMessageForm(instance=push_message)
    return render(request, 'notification/edit.html', {'msg': push_message, 'form': form})


class PageRangeListView(ListView):
    def get_page_range(self, page, paginator):
        # Get the index of the current page
        index = page.number - 1  # edited to something easier without index
        # This value is maximum index of your pages, so the last page - 1
        max_index = len(paginator.page_range)
        # You want a range of 7, so lets calculate where to slice the list
        start_index = index - 3 if index >= 3 else 0
        end_index = index + 3 if index <= max_index - 3 else max_index
        # Get our new page range. In the latest versions of Django page_range returns
        # an iterator. Thus pass it to list, to make our slice possible again.
        page_range = list(paginator.page_range)[start_index:end_index]
        return page_range


class PushMessageList(LoginRequiredMixin, PageRangeListView):
    paginate_by = 10
    model = PushMessage
    # context_object_name = 'message_list'
    ordering = ['-created_at']
    template_name = 'notification/messages.html'

    def get_queryset(self):
        title = self.request.GET.get('title')
        type = self.request.GET.get('type')

        object_list = self.model.objects.all()
        if title:
            object_list = object_list.filter(title__icontains=title)

        if type:
            object_list = object_list.filter(type=type)

        object_list = object_list.order_by('-created_at')
        return object_list

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_range'] = self.get_page_range(context['page_obj'], context['paginator'])
        context['search_form'] = SearchMessageForm(self.request.GET)
        return context


@login_required
def message_details(request, message_id):
    try:
        push_message = PushMessage.objects.get(pk=message_id)
    except PushMessage.DoesNotExist:
        raise Http404("Message does not exist")
    return render(request, 'notification/message_details.html', {'message': push_message})


class BulkMessageRequestList(LoginRequiredMixin, PageRangeListView):
    paginate_by = 10
    model = BulkNotificationRequest
    ordering = ['-created_at']
    template_name = 'notification/bulk_push/list.html'

    def get_queryset(self):
        title = self.request.GET.get('title')

        object_list = self.model.objects.filter(receiver_type=ReceiverType.FILE.name)
        if title:
            object_list = object_list.filter(title__icontains=title)

        object_list = object_list.order_by('-created_at')
        return object_list

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_range'] = self.get_page_range(context['page_obj'], context['paginator'])
        context['search_form'] = SearchBulkMessageForm(self.request.GET)
        return context


class BulkMessageReceiversList(LoginRequiredMixin, PageRangeListView):
    paginate_by = 10
    model = BulkNotificationReceiver
    ordering = ['-created_at']
    template_name = 'notification/bulk_push/receivers.html'

    def get_queryset(self):
        mobile = self.request.GET.get('mobile')

        object_list = self.model.objects.filter(request_id=self.kwargs['request_id'])
        if mobile:
            object_list = object_list.filter(mobile__icontains=mobile)

        object_list = object_list.order_by('-created_at')
        return object_list

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_range'] = self.get_page_range(context['page_obj'], context['paginator'])
        context['bulk_request'] = BulkNotificationRequest.objects.select_related('message').get(
            pk=self.kwargs['request_id']
        )
        context['search_form'] = SearchBulkMessageReceiverForm(self.request.GET)
        return context


class BulkNotificationRequestView(LoginRequiredMixin, ListView):
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        bulk_request = BulkNotificationRequest.objects.select_related('message').get(pk=self.kwargs['request_id'])
        context['bulk_request'] = bulk_request
        if bulk_request.receiver_type == ReceiverType.FILE.name:
            bulk_file = BulkNotificationFile.objects.get(request=bulk_request)
            context['file_url'] = bulk_file.uploaded_file.url
        return context


class BulkMessageSendRequestView(BulkNotificationRequestView):
    model = BulkNotificationSendRequest
    template_name = 'notification/bulk_push/send_requests.html'

    def get_queryset(self):
        request_id = self.kwargs['request_id']
        return self.model.objects.filter(request_id=request_id, ).order_by('-created_at')


class BulkMessageSchedulesView(BulkNotificationRequestView):
    model = BulkNotificationSchedule
    template_name = 'notification/bulk_push/schedules.html'

    def get_queryset(self):
        request_id = self.kwargs['request_id']
        return self.model.objects.filter(request_id=request_id, ).order_by('-created_at')


class BulkMessageTagsView(BulkNotificationRequestView):
    template_name = 'notification/tg_push/tags.html'

    def get_queryset(self):
        request_id = self.kwargs['request_id']
        bulk_request = BulkNotificationRequest.objects.get(pk=request_id)
        return bulk_request.receiving_tags.all()


class SendBulkMessage(LoginRequiredMixin, View):
    def get(self, request, request_id):
        context = {
            'bulk_request': BulkNotificationRequest.objects.select_related('message').get(pk=request_id)
        }
        return render(request, 'notification/bulk_push/send.html', context)

    def post(self, request, request_id):
        serializer = SendBulkNotificationSerializer(data=request.POST)
        is_scheduled = False
        if serializer.is_valid(raise_exception=True):
            request_data = serializer.save()
            is_scheduled = schedule_bulk_notification(request_id, request_data, request.user.username)

        if is_scheduled:
            return redirect('bulk_message_schedules', request_id)
        else:
            return redirect('bulk_message_send_request', request_id)
